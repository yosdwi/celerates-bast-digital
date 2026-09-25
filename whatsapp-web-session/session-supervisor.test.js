"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { SessionSupervisor } = require("./session-supervisor");

function fixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wwjs-supervisor-"));
  return { dir, statePath: path.join(dir, "supervisor.json") };
}

function subject(f, overrides = {}) {
  let restarts = 0;
  const state = {
    connection: "disconnected",
    connectionChangedAt: new Date(Date.now() - 60_000),
    operatorActionRequired: false,
    operatorReason: "",
    ...overrides.state,
  };
  const bridge = {
    ready: false,
    isReady() {
      return this.ready;
    },
    async restartTransient() {
      restarts += 1;
    },
    ...overrides.bridge,
  };
  const supervisor = new SessionSupervisor({
    state,
    bridge,
    filePath: f.statePath,
    ownerGuard: overrides.ownerGuard || { acquired: true },
    storageSafety: overrides.storageSafety || { healthy: true },
    probeMs: 60_000,
    graceMs: 1,
    maxAttempts: overrides.maxAttempts || 3,
    cooldownMs: 60_000,
  });
  return { supervisor, bridge, state, restarts: () => restarts };
}

test("transient disconnect starts bounded reconnect without logout or auth reset", async () => {
  const f = fixture();
  const s = subject(f);
  try {
    const result = await s.supervisor.probe();
    assert.deepEqual(result, { recovered: true, reason: "reconnect_started" });
    assert.equal(s.restarts(), 1);
    assert.equal(s.supervisor.snapshot().attempts_in_window, 1);
    assert.equal(s.supervisor.snapshot().recovery_state, "observing");
  } finally {
    s.supervisor.stop();
    fs.rmSync(f.dir, { recursive: true, force: true });
  }
});

test("operator-action-required blocks automatic reconnect", async () => {
  const f = fixture();
  const s = subject(f, {
    state: { operatorActionRequired: true, operatorReason: "logged-out: LOGOUT" },
  });
  try {
    const result = await s.supervisor.probe();
    assert.equal(result.reason, "operator_action_required");
    assert.equal(s.restarts(), 0);
    assert.equal(s.supervisor.snapshot().recovery_state, "operator_action_required");
  } finally {
    s.supervisor.stop();
    fs.rmSync(f.dir, { recursive: true, force: true });
  }
});

test("pause is durable and suppresses recovery after process restart", async () => {
  const f = fixture();
  const first = subject(f);
  try {
    first.supervisor.pause();
    const second = subject(f);
    const result = await second.supervisor.probe();
    assert.equal(result.reason, "paused");
    assert.equal(second.restarts(), 0);
    assert.equal(second.supervisor.snapshot().paused, true);
    second.supervisor.stop();
  } finally {
    first.supervisor.stop();
    fs.rmSync(f.dir, { recursive: true, force: true });
  }
});

test("recovery budget enters durable cooldown instead of looping reconnect", async () => {
  const f = fixture();
  const s = subject(f, { maxAttempts: 1 });
  try {
    await s.supervisor.probe();
    const second = await s.supervisor.probe();
    assert.equal(second.reason, "budget_exhausted");
    assert.equal(s.restarts(), 1);
    assert.equal(s.supervisor.snapshot().recovery_state, "cooldown");
    assert.ok(s.supervisor.snapshot().cooldown_until);
  } finally {
    s.supervisor.stop();
    fs.rmSync(f.dir, { recursive: true, force: true });
  }
});
