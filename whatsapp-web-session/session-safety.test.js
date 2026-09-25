"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  SessionOwnerGuard,
  clearStaleChromiumLocks,
  inspectSessionStorage,
} = require("./session-safety");

function fixture() {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "wwjs-safety-"));
  const authDir = path.join(dataDir, "auth-whatsapp-web-js");
  fs.mkdirSync(authDir, { recursive: true });
  return { dataDir, authDir, ownerPath: path.join(dataDir, "wwjs-owner.json") };
}

test("only one fresh owner lease can hold the shared whatsapp session", () => {
  const f = fixture();
  let now = Date.now();
  const first = new SessionOwnerGuard({ filePath: f.ownerPath, ttlMs: 1000, now: () => now });
  const second = new SessionOwnerGuard({ filePath: f.ownerPath, ttlMs: 1000, now: () => now });
  try {
    assert.equal(first.acquire(), true);
    assert.equal(second.acquire(), false);
    assert.equal(second.snapshot().conflict_owner_id, first.ownerId);

    first.timer && clearInterval(first.timer);
    first.timer = null;
    now += 1500;
    assert.equal(second.acquire(), true);
    assert.equal(second.snapshot().acquired, true);
  } finally {
    first.release();
    second.release();
    fs.rmSync(f.dataDir, { recursive: true, force: true });
  }
});

test("chromium singleton cleanup is blocked without the owner lease", () => {
  const f = fixture();
  const lock = path.join(f.authDir, "SingletonLock");
  fs.writeFileSync(lock, "stale");
  const guard = new SessionOwnerGuard({ filePath: f.ownerPath });
  const storage = inspectSessionStorage({ dataDir: f.dataDir, authDir: f.authDir, minFreeBytes: 1 });
  try {
    const blocked = clearStaleChromiumLocks(f.authDir, {
      ownerGuard: guard,
      storageSafety: storage,
    });
    assert.equal(blocked.blocked, "session_owner_not_acquired");
    assert.equal(fs.existsSync(lock), true);

    assert.equal(guard.acquire(), true);
    const cleared = clearStaleChromiumLocks(f.authDir, {
      ownerGuard: guard,
      storageSafety: storage,
    });
    assert.equal(cleared.blocked, null);
    assert.equal(cleared.cleared, 1);
    assert.equal(fs.existsSync(lock), false);
  } finally {
    guard.release();
    fs.rmSync(f.dataDir, { recursive: true, force: true });
  }
});

test("storage safety rejects a symlinked auth authority", () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "wwjs-safety-link-"));
  const realAuth = path.join(dataDir, "real-auth");
  const authDir = path.join(dataDir, "auth-whatsapp-web-js");
  fs.mkdirSync(realAuth);
  fs.symlinkSync(realAuth, authDir, "dir");
  try {
    const result = inspectSessionStorage({ dataDir, authDir, minFreeBytes: 1 });
    assert.equal(result.healthy, false);
    assert.ok(result.reasons.includes("auth_dir_symlink"));
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});
