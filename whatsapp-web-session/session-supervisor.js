"use strict";

const fs = require("node:fs");
const path = require("node:path");

const POLICY_VERSION = 1;
const DEFAULT_PROBE_MS = 15_000;
const DEFAULT_GRACE_MS = 30_000;
const DEFAULT_WINDOW_MS = 15 * 60_000;
const DEFAULT_COOLDOWN_MS = 15 * 60_000;
const DEFAULT_MAX_ATTEMPTS = 3;
const TRANSIENT_CONNECTIONS = new Set(["disconnected", "failed"]);

function positiveNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

class SessionSupervisor {
  constructor({
    state,
    bridge,
    filePath,
    ownerGuard,
    storageSafety,
    probeMs = DEFAULT_PROBE_MS,
    graceMs = DEFAULT_GRACE_MS,
    windowMs = DEFAULT_WINDOW_MS,
    cooldownMs = DEFAULT_COOLDOWN_MS,
    maxAttempts = DEFAULT_MAX_ATTEMPTS,
    logf = () => {},
    now = () => Date.now(),
  }) {
    this.state = state;
    this.bridge = bridge;
    this.filePath = filePath;
    this.ownerGuard = ownerGuard;
    this.storageSafety = storageSafety;
    this.probeMs = positiveNumber(probeMs, DEFAULT_PROBE_MS);
    this.graceMs = positiveNumber(graceMs, DEFAULT_GRACE_MS);
    this.windowMs = positiveNumber(windowMs, DEFAULT_WINDOW_MS);
    this.cooldownMs = positiveNumber(cooldownMs, DEFAULT_COOLDOWN_MS);
    this.maxAttempts = Math.max(1, Number(maxAttempts) || DEFAULT_MAX_ATTEMPTS);
    this.logf = logf;
    this.now = now;
    this.timer = null;
    this.runningProbe = null;
    this.data = {
      version: 1,
      policy_version: POLICY_VERSION,
      applied_policy_version: POLICY_VERSION,
      paused: false,
      recovery_state: "starting",
      recovery_reason: "",
      last_probe_at: null,
      last_ready_at: null,
      last_ack_at: null,
      cooldown_until: null,
      attempts: [],
    };
    this._load();
  }

  _load() {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.filePath, "utf8"));
      if (parsed && parsed.version === 1) {
        this.data = {
          ...this.data,
          ...parsed,
          attempts: Array.isArray(parsed.attempts) ? parsed.attempts : [],
        };
      }
    } catch (err) {
      if (err && err.code !== "ENOENT") this.logf(`supervisor state load failed: ${err.message}`);
    }
  }

  _persist() {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true, mode: 0o750 });
    const temporary = `${this.filePath}.tmp-${process.pid}`;
    fs.writeFileSync(temporary, `${JSON.stringify(this.data)}\n`, { mode: 0o640 });
    fs.renameSync(temporary, this.filePath);
  }

  _iso(timestamp = this.now()) {
    return new Date(timestamp).toISOString();
  }

  _pruneAttempts() {
    const cutoff = this.now() - this.windowMs;
    this.data.attempts = this.data.attempts.filter((value) => Date.parse(value) >= cutoff);
  }

  _setRecovery(state, reason = "") {
    this.data.recovery_state = state;
    this.data.recovery_reason = reason;
    this._persist();
  }

  start() {
    if (this.timer) return;
    this.timer = setInterval(() => {
      this.probe().catch((err) => this.logf(`supervisor probe failed: ${err.stack || err}`));
    }, this.probeMs);
    this.timer.unref?.();
    this.probe().catch((err) => this.logf(`initial supervisor probe failed: ${err.stack || err}`));
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  pause() {
    this.data.paused = true;
    this._setRecovery("paused", "operator_paused");
  }

  resume() {
    this.data.paused = false;
    this.data.cooldown_until = null;
    this._setRecovery("observing", "operator_resumed");
    this.probe().catch((err) => this.logf(`resume probe failed: ${err.message}`));
  }

  markAck() {
    this.data.last_ack_at = this._iso();
    this._persist();
  }

  async requestReconnect() {
    if (this.state.operatorActionRequired) return { accepted: false, reason: "operator_action_required" };
    if (!this.ownerGuard.acquired) return { accepted: false, reason: "session_owner_not_acquired" };
    if (!this.storageSafety.healthy) return { accepted: false, reason: "session_storage_unhealthy" };
    if (this.bridge.isReady()) return { accepted: false, reason: "already_ready" };
    if (this.runningProbe) return { accepted: false, reason: "recovery_in_progress" };
    this.data.paused = false;
    this.data.cooldown_until = null;
    return this._recover("operator_reconnect");
  }

  async probe() {
    if (this.runningProbe) return this.runningProbe;
    this.runningProbe = this._probeOnce();
    try {
      return await this.runningProbe;
    } finally {
      this.runningProbe = null;
    }
  }

  async _probeOnce() {
    const now = this.now();
    this.data.last_probe_at = this._iso(now);
    this._pruneAttempts();

    if (!this.ownerGuard.acquired) {
      this._setRecovery("blocked", "session_owner_not_acquired");
      return { recovered: false, reason: "session_owner_not_acquired" };
    }
    if (!this.storageSafety.healthy) {
      this._setRecovery("blocked", "session_storage_unhealthy");
      return { recovered: false, reason: "session_storage_unhealthy" };
    }
    if (this.state.operatorActionRequired) {
      this._setRecovery("operator_action_required", this.state.operatorReason || "pairing_required");
      return { recovered: false, reason: "operator_action_required" };
    }
    if (this.data.paused) {
      this._setRecovery("paused", "operator_paused");
      return { recovered: false, reason: "paused" };
    }
    if (this.bridge.isReady()) {
      this.data.last_ready_at = this._iso(now);
      this.data.cooldown_until = null;
      this._setRecovery("connected", "");
      return { recovered: false, reason: "ready" };
    }

    const connection = String(this.state.connection || "");
    if (!TRANSIENT_CONNECTIONS.has(connection)) {
      this._setRecovery("observing", connection || "not_ready");
      return { recovered: false, reason: "not_transient" };
    }

    const changedAt = new Date(this.state.connectionChangedAt).getTime();
    if (Number.isFinite(changedAt) && now - changedAt < this.graceMs) {
      this._setRecovery("observing", "transient_grace_period");
      return { recovered: false, reason: "grace_period" };
    }

    const cooldownUntil = Date.parse(String(this.data.cooldown_until || ""));
    if (Number.isFinite(cooldownUntil) && now < cooldownUntil) {
      this._setRecovery("cooldown", "recovery_budget_exhausted");
      return { recovered: false, reason: "cooldown" };
    }
    if (this.data.attempts.length >= this.maxAttempts) {
      this.data.cooldown_until = this._iso(now + this.cooldownMs);
      this._setRecovery("cooldown", "recovery_budget_exhausted");
      return { recovered: false, reason: "budget_exhausted" };
    }

    return this._recover("transient_disconnect");
  }

  async _recover(reason) {
    const now = this.now();
    this.data.attempts.push(this._iso(now));
    this._setRecovery("recovering", reason);
    this.logf(`supervisor recovery attempt ${this.data.attempts.length}/${this.maxAttempts}: ${reason}`);
    try {
      await this.bridge.restartTransient();
      this._setRecovery("observing", "reconnect_started");
      return { recovered: true, reason: "reconnect_started" };
    } catch (err) {
      this.logf(`supervisor reconnect failed: ${err.stack || err}`);
      this._setRecovery("observing", "reconnect_failed");
      return { recovered: false, reason: "reconnect_failed" };
    }
  }

  snapshot() {
    return {
      paused: Boolean(this.data.paused),
      recovery_state: this.data.recovery_state,
      recovery_reason: this.data.recovery_reason || null,
      last_probe_at: this.data.last_probe_at,
      last_ready_at: this.data.last_ready_at,
      last_ack_at: this.data.last_ack_at,
      cooldown_until: this.data.cooldown_until,
      attempts_in_window: this.data.attempts.length,
      max_attempts: this.maxAttempts,
      policy_version: POLICY_VERSION,
      applied_policy_version: this.data.applied_policy_version,
    };
  }
}

module.exports = { SessionSupervisor, POLICY_VERSION };
