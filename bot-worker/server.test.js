"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { safeEqual, cliArgsFor, executionFor } = require("./server");

test("safeEqual only accepts equal non-empty tokens", () => {
  assert.equal(safeEqual("secret-value", "secret-value"), true);
  assert.equal(safeEqual("secret-value", "other-value"), false);
  assert.equal(safeEqual("", ""), false);
  assert.equal(safeEqual(undefined, "secret-value"), false);
});

test("cliArgsFor maps a text reply without a jid/channel", () => {
  assert.deepEqual(cliArgsFor({ kind: "text", text: "status 1 sampai 31 Agustus" }), [
    "bot-reply",
    "--text",
    "status 1 sampai 31 Agustus",
  ]);
});

test("cliArgsFor maps a DM text reply with jid, channel and message timestamp", () => {
  assert.deepEqual(
    cliArgsFor({
      kind: "text",
      text: "halo",
      jid: "628123@s.whatsapp.net",
      channel: "dm",
      message_at: "2026-09-08T01:30:00.000Z",
    }),
    [
      "bot-reply",
      "--text",
      "halo",
      "--jid",
      "628123@s.whatsapp.net",
      "--channel",
      "dm",
      "--message-at",
      "2026-09-08T01:30:00.000Z",
    ],
  );
});

test("cliArgsFor keeps legacy DM payload valid when timestamp is absent", () => {
  assert.deepEqual(
    cliArgsFor({ kind: "text", text: "halo", jid: "628123@s.whatsapp.net", channel: "dm" }),
    ["bot-reply", "--text", "halo", "--jid", "628123@s.whatsapp.net", "--channel", "dm"],
  );
});

test("cliArgsFor maps an evidence upload", () => {
  assert.deepEqual(
    cliArgsFor({
      kind: "evidence",
      jid: "628123@s.whatsapp.net",
      filePath: "/data/evidence-uploads/1-a.jpg",
      caption: "bukti kerja",
    }),
    [
      "bot-evidence",
      "--jid",
      "628123@s.whatsapp.net",
      "--file",
      "/data/evidence-uploads/1-a.jpg",
      "--caption",
      "bukti kerja",
    ],
  );
});

test("executionFor routes group replies through the PMO group entry wrapper", () => {
  const execution = executionFor(["bot-reply", "--text", "cek status tasklist iot"]);
  assert.equal(execution.command, "python");
  assert.deepEqual(execution.args, [
    "-m",
    "digital_bast.bot.group_entry",
    "reply",
    "--text",
    "cek status tasklist iot",
  ]);
});

test("executionFor routes timestamped DM through the payroll-aware Python entry wrapper", () => {
  const execution = executionFor([
    "bot-reply",
    "--text",
    "17:00",
    "--jid",
    "628123@s.whatsapp.net",
    "--channel",
    "dm",
    "--message-at",
    "2026-09-08T01:30:00.000Z",
  ]);
  assert.equal(execution.command, "python");
  assert.deepEqual(execution.args, [
    "-m",
    "digital_bast.bot.dm_message_entry",
    "reply",
    "--text",
    "17:00",
    "--jid",
    "628123@s.whatsapp.net",
    "--message-at",
    "2026-09-08T01:30:00.000Z",
  ]);
});

test("executionFor keeps legacy DM entry when timestamp is absent", () => {
  const execution = executionFor([
    "bot-reply",
    "--text",
    "17:00",
    "--jid",
    "628123@s.whatsapp.net",
    "--channel",
    "dm",
  ]);
  assert.deepEqual(execution.args, [
    "-m",
    "digital_bast.bot.dm_entry",
    "reply",
    "--text",
    "17:00",
    "--jid",
    "628123@s.whatsapp.net",
  ]);
});

test("executionFor routes evidence through the existing Python DM workflow wrapper", () => {
  const execution = executionFor([
    "bot-evidence",
    "--jid",
    "628123@s.whatsapp.net",
    "--file",
    "/data/evidence-uploads/1-a.jpg",
    "--caption",
    "bukti kerja",
  ]);
  assert.equal(execution.command, "python");
  assert.deepEqual(execution.args, [
    "-m",
    "digital_bast.bot.dm_workflow",
    "evidence",
    "--jid",
    "628123@s.whatsapp.net",
    "--file",
    "/data/evidence-uploads/1-a.jpg",
    "--caption",
    "bukti kerja",
  ]);
});

test("cliArgsFor rejects malformed or unknown payloads", () => {
  assert.equal(cliArgsFor(null), null);
  assert.equal(cliArgsFor({ kind: "text" }), null);
  assert.equal(cliArgsFor({ kind: "evidence", jid: "628123@s.whatsapp.net" }), null);
  assert.equal(cliArgsFor({ kind: "unknown" }), null);
});

// ---- async jobs: a slow command is handed back as a job instead of holding the connection ----
//
// These start the real HTTP server with a fake interpreter (a shell script) standing in for
// `python -m digital_bast.bot.group_entry reply --text <text>`: text "slow" takes 700ms, anything
// else answers at once. The inline window is 150ms so "slow" always becomes a job.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const asyncDir = fs.mkdtempSync(path.join(os.tmpdir(), "bot-worker-async-"));
const fakePython = path.join(asyncDir, "fake-python.sh");
fs.writeFileSync(
  fakePython,
  '#!/bin/sh\n# args: -m digital_bast.bot.group_entry reply --text <text>\n[ "$5" = "slow" ] && sleep 0.7\n[ "$5" = "boom" ] && { echo "traceback" >&2; exit 3; }\necho "{\\"kind\\":\\"text\\",\\"echo\\":\\"$5\\"}"\n',
  { mode: 0o755 },
);
fs.writeFileSync(path.join(asyncDir, "token"), "test-bridge-token\n");

function startWorker() {
  // Constants are read at load time, so run the server in a child that has the env set.
  const code = `
    const s = require(${JSON.stringify(path.join(__dirname, "server.js"))});
    s.server.listen(0, "127.0.0.1", () => console.log(s.server.address().port));
  `;
  const { spawn } = require("node:child_process");
  const child = spawn(process.execPath, ["-e", code], {
    env: {
      ...process.env,
      BAST_PYTHON: fakePython,
      BAST_INLINE_WAIT_MS: "150",
      BOT_BRIDGE_TOKEN_FILE: path.join(asyncDir, "token"),
    },
    stdio: ["ignore", "pipe", "inherit"],
  });
  return new Promise((resolve, reject) => {
    child.stdout.once("data", (d) => resolve({ child, base: `http://127.0.0.1:${String(d).trim()}` }));
    child.once("error", reject);
  });
}

const post = (base, body, token = "test-bridge-token") =>
  fetch(`${base}/internal/v1/reply`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-bridge-token": token },
    body: JSON.stringify(body),
  });
const getJob = (base, id, token = "test-bridge-token") =>
  fetch(`${base}/internal/v1/jobs/${id}`, { headers: { "x-bridge-token": token } });

test("async worker: fast commands answer inline, slow ones become a pollable job, old callers still wait", async (t) => {
  const { child, base } = await startWorker();
  t.after(() => child.kill());

  const fast = await post(base, { kind: "text", text: "fast", async: true });
  assert.equal(fast.status, 200);
  assert.deepEqual(await fast.json(), { ok: true, text: '{"kind":"text","echo":"fast"}' });

  const slow = await post(base, { kind: "text", text: "slow", async: true });
  assert.equal(slow.status, 202);
  const accepted = await slow.json();
  assert.equal(accepted.pending, true);
  assert.match(accepted.job_id, /^[0-9a-f-]{36}$/);

  const running = await getJob(base, accepted.job_id);
  assert.equal(running.status, 200);
  assert.deepEqual(await running.json(), { state: "running" });

  await new Promise((resolve) => setTimeout(resolve, 900));
  const done = await getJob(base, accepted.job_id);
  assert.deepEqual(await done.json(), { state: "done", ok: true, text: '{"kind":"text","echo":"slow"}' });
  assert.equal((await getJob(base, accepted.job_id)).status, 200, "a finished job can be read again (retry-safe)");

  // A caller that does not send `async` (the previous wa-session) keeps the synchronous contract.
  const legacy = await post(base, { kind: "text", text: "slow" });
  assert.equal(legacy.status, 200);
  assert.deepEqual(await legacy.json(), { ok: true, text: '{"kind":"text","echo":"slow"}' });
});

test("async worker: a failing job reports ok=false with its stderr; unknown ids and bad tokens are refused", async (t) => {
  const { child, base } = await startWorker();
  t.after(() => child.kill());

  const failing = await (await post(base, { kind: "text", text: "boom", async: true })).json();
  assert.equal(failing.ok, false, "a fast failure is still answered inline");
  assert.match(failing.text, /traceback/);

  assert.equal((await post(base, { kind: "text", text: "x", async: true }, "wrong")).status, 403);
  assert.equal((await getJob(base, "00000000-0000-4000-8000-000000000000")).status, 404);
  assert.equal((await getJob(base, "00000000-0000-4000-8000-000000000000", "wrong")).status, 403);
  assert.equal((await fetch(`${base}/internal/v1/jobs/not-a-uuid`)).status, 404);
});

test("finished jobs expire after an hour and the finished-job list is bounded", () => {
  const { jobs, pruneJobs } = require("./server");
  jobs.clear();
  const now = Date.now();
  jobs.set("old", { state: "done", finishedAt: now - 61 * 60 * 1000, result: { ok: true, text: "" } });
  jobs.set("running", { state: "running", startedAt: now - 99 * 60 * 1000, finishedAt: 0, result: null });
  for (let i = 0; i < 60; i++) jobs.set(`f${i}`, { state: "done", finishedAt: now - i, result: { ok: true, text: "" } });

  pruneJobs(now);

  assert.equal(jobs.has("old"), false);
  assert.equal(jobs.has("running"), true, "a running job is never dropped");
  assert.equal([...jobs.values()].filter((j) => j.state === "done").length, 50);
  assert.equal(jobs.has("f0"), true, "the newest finished jobs are the ones kept");
  assert.equal(jobs.has("f59"), false);
  jobs.clear();
  spawnSync("true");
});

test("wa-session's client and the real worker agree on the job protocol end to end", async (t) => {
  const { callWorker } = require("../whatsapp-web-session/worker-client");
  const { child, base } = await startWorker();
  t.after(() => child.kill());
  const common = { baseUrl: base, token: "test-bridge-token", totalTimeoutMs: 10_000, pollIntervalMs: 50 };

  const fast = await callWorker({ ...common, payload: { kind: "text", text: "fast" } });
  assert.deepEqual(fast, { ok: true, text: '{"kind":"text","echo":"fast"}' });

  const started = Date.now();
  const slow = await callWorker({ ...common, payload: { kind: "text", text: "slow" } });
  assert.deepEqual(slow, { ok: true, text: '{"kind":"text","echo":"slow"}' });
  assert.ok(Date.now() - started >= 600, "it really waited for the slow command (as a job)");

  const wrongToken = await callWorker({ ...common, token: "wrong", payload: { kind: "text", text: "fast" } });
  assert.equal(wrongToken.ok, false);
});
