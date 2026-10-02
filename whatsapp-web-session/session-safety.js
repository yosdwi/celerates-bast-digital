"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const DEFAULT_OWNER_TTL_MS = 90_000;
const DEFAULT_HEARTBEAT_MS = 15_000;
const DEFAULT_MIN_FREE_BYTES = 128 * 1024 * 1024;
const DEFAULT_MIN_FREE_INODES = 256;

function asMillis(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function inspectSessionStorage({
  dataDir,
  authDir,
  minFreeBytes = DEFAULT_MIN_FREE_BYTES,
  minFreeInodes = DEFAULT_MIN_FREE_INODES,
}) {
  const reasons = [];
  let freeBytes = null;
  let freeInodes = null;
  try {
    fs.mkdirSync(dataDir, { recursive: true, mode: 0o750 });
    fs.mkdirSync(authDir, { recursive: true, mode: 0o750 });
    const authStat = fs.lstatSync(authDir);
    if (authStat.isSymbolicLink()) reasons.push("auth_dir_symlink");
    fs.accessSync(dataDir, fs.constants.R_OK | fs.constants.W_OK);
    fs.accessSync(authDir, fs.constants.R_OK | fs.constants.W_OK);

    const probePath = path.join(dataDir, `.wwjs-write-probe-${process.pid}`);
    fs.writeFileSync(probePath, "ok", { mode: 0o600 });
    fs.rmSync(probePath, { force: true });

    if (typeof fs.statfsSync === "function") {
      const stats = fs.statfsSync(dataDir);
      freeBytes = Number(stats.bavail) * Number(stats.bsize);
      freeInodes = Number(stats.ffree);
      if (Number.isFinite(freeBytes) && freeBytes < minFreeBytes) reasons.push("low_disk_space");
      if (Number.isFinite(freeInodes) && freeInodes < minFreeInodes) reasons.push("low_free_inodes");
    }
  } catch (err) {
    reasons.push(`storage_check_failed:${err.code || err.message}`);
  }
  return {
    healthy: reasons.length === 0,
    reasons,
    free_bytes: freeBytes,
    free_inodes: freeInodes,
  };
}

class SessionOwnerGuard {
  constructor({
    filePath,
    ttlMs = DEFAULT_OWNER_TTL_MS,
    heartbeatMs = DEFAULT_HEARTBEAT_MS,
    logf = () => {},
    now = () => Date.now(),
  }) {
    this.filePath = filePath;
    this.ttlMs = asMillis(ttlMs, DEFAULT_OWNER_TTL_MS);
    this.heartbeatMs = asMillis(heartbeatMs, DEFAULT_HEARTBEAT_MS);
    this.logf = logf;
    this.now = now;
    this.ownerId = crypto.randomUUID();
    this.acquired = false;
    this.conflict = null;
    this.timer = null;
  }

  _record() {
    const now = new Date(this.now()).toISOString();
    return {
      version: 1,
      owner_id: this.ownerId,
      pid: process.pid,
      started_at: this.startedAt || now,
      heartbeat_at: now,
    };
  }

  _writeExclusive() {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true, mode: 0o750 });
    const fd = fs.openSync(this.filePath, "wx", 0o640);
    try {
      fs.writeFileSync(fd, `${JSON.stringify(this._record())}\n`);
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
  }

  _readExisting() {
    try {
      return JSON.parse(fs.readFileSync(this.filePath, "utf8"));
    } catch {
      return null;
    }
  }

  _isFresh(record) {
    const heartbeat = Date.parse(String(record?.heartbeat_at || ""));
    return Number.isFinite(heartbeat) && this.now() - heartbeat <= this.ttlMs;
  }

  acquire() {
    this.startedAt = new Date(this.now()).toISOString();
    try {
      this._writeExclusive();
    } catch (err) {
      if (err.code !== "EEXIST") throw err;
      const existing = this._readExisting();
      if (existing && this._isFresh(existing)) {
        this.conflict = existing;
        return false;
      }
      const quarantine = `${this.filePath}.stale-${this.now()}-${crypto.randomBytes(3).toString("hex")}`;
      try {
        fs.renameSync(this.filePath, quarantine);
      } catch (renameError) {
        this.conflict = this._readExisting();
        this.logf(`session owner stale takeover lost race: ${renameError.message}`);
        return false;
      }
      try {
        this._writeExclusive();
        fs.rmSync(quarantine, { force: true });
      } catch (createError) {
        this.conflict = this._readExisting();
        this.logf(`session owner takeover failed: ${createError.message}`);
        return false;
      }
    }
    this.acquired = true;
    this.conflict = null;
    this._startHeartbeat();
    return true;
  }

  _startHeartbeat() {
    if (this.timer) clearInterval(this.timer);
    this.timer = setInterval(() => this.heartbeat(), this.heartbeatMs);
    this.timer.unref?.();
  }

  heartbeat() {
    if (!this.acquired) return false;
    const existing = this._readExisting();
    if (!existing || existing.owner_id !== this.ownerId) {
      this.acquired = false;
      this.conflict = existing;
      if (this.timer) clearInterval(this.timer);
      this.timer = null;
      this.logf("session owner lease lost; automatic recovery disabled");
      return false;
    }
    const temporary = `${this.filePath}.tmp-${this.ownerId}`;
    fs.writeFileSync(temporary, `${JSON.stringify(this._record())}\n`, { mode: 0o640 });
    fs.renameSync(temporary, this.filePath);
    return true;
  }

  release() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    const existing = this._readExisting();
    if (existing?.owner_id === this.ownerId) fs.rmSync(this.filePath, { force: true });
    this.acquired = false;
  }

  snapshot() {
    return {
      acquired: this.acquired,
      owner_id: this.acquired ? this.ownerId : null,
      conflict_owner_id: this.conflict?.owner_id || null,
      conflict_heartbeat_at: this.conflict?.heartbeat_at || null,
      ttl_ms: this.ttlMs,
    };
  }
}

function clearStaleChromiumLocks(authDir, { ownerGuard, storageSafety, logf = () => {} }) {
  if (!ownerGuard?.acquired) return { cleared: 0, blocked: "session_owner_not_acquired" };
  if (!storageSafety?.healthy) return { cleared: 0, blocked: "session_storage_unhealthy" };

  let cleared = 0;
  const stack = [authDir];
  while (stack.length) {
    const dir = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        stack.push(full);
      } else if (/^Singleton(Lock|Socket|Cookie)$/.test(entry.name)) {
        try {
          fs.rmSync(full, { force: true });
          cleared += 1;
        } catch (err) {
          logf(`failed to clear stale Chromium lock ${full}: ${err.message}`);
        }
      }
    }
  }
  return { cleared, blocked: null };
}

module.exports = {
  SessionOwnerGuard,
  clearStaleChromiumLocks,
  inspectSessionStorage,
};
