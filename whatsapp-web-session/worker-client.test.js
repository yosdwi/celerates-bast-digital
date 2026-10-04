"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const { callWorker } = require("./worker-client");

const JOB = "11111111-2222-4333-8444-555555555555";

// A scripted bot-worker: `reply` decides the POST answer, `polls` the answers to successive job polls.
function fakeWorker({ reply, polls = [] }) {
  const seen = { posts: [], polls: 0, headers: [] };
  const server = http.createServer((req, res) => {
    seen.headers.push(req.headers["x-bridge-token"]);
    if (req.method === "POST") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        seen.posts.push(JSON.parse(body));
        const [status, json] = reply;
        res.writeHead(status, { "content-type": "application/json" });
        res.end(JSON.stringify(json));
      });
      return;
    }
    const answer = polls[Math.min(seen.polls, polls.length - 1)];
    seen.polls += 1;
    if (answer === "hang") return;
    const [status, json] = answer;
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(json));
  });
  return new Promise((resolve) =>
    server.listen(0, "127.0.0.1", () => resolve({ server, seen, baseUrl: `http://127.0.0.1:${server.address().port}` })),
  );
}

const options = (baseUrl, extra = {}) => ({
  baseUrl,
  token: "t0ken",
  payload: { kind: "text", text: "export bast september untuk shifting" },
  totalTimeoutMs: 5_000,
  pollIntervalMs: 1,
  sleep: () => new Promise((r) => setTimeout(r, 1)),
  ...extra,
});

test("a fast answer comes back from the first request; the request asks for job mode", async (t) => {
  const { server, seen, baseUrl } = await fakeWorker({ reply: [200, { ok: true, text: "halo" }] });
  t.after(() => server.close());

  assert.deepEqual(await callWorker(options(baseUrl)), { ok: true, text: "halo" });
  assert.equal(seen.posts[0].async, true);
  assert.equal(seen.posts[0].text, "export bast september untuk shifting");
  assert.equal(seen.headers[0], "t0ken");
  assert.equal(seen.polls, 0);
});

test("a slow command is polled until it is done and its result is returned as-is", async (t) => {
  const file = JSON.stringify({ kind: "file", path: "/data/exports/BAST_iotoperation_2026-09.pdf" });
  const { server, seen, baseUrl } = await fakeWorker({
    reply: [202, { ok: true, pending: true, job_id: JOB }],
    polls: [[200, { state: "running" }], [200, { state: "running" }], [200, { state: "done", ok: true, text: file }]],
  });
  t.after(() => server.close());

  assert.deepEqual(await callWorker(options(baseUrl)), { ok: true, text: file });
  assert.equal(seen.polls, 3);
});

test("a job that fails reports ok=false with the worker's text", async (t) => {
  const { server, baseUrl } = await fakeWorker({
    reply: [202, { ok: true, pending: true, job_id: JOB }],
    polls: [[200, { state: "done", ok: false, text: "renderer down" }]],
  });
  t.after(() => server.close());

  assert.deepEqual(await callWorker(options(baseUrl)), { ok: false, text: "renderer down" });
});

test("a worker restart (job unknown) is reported, not retried forever", async (t) => {
  const { server, baseUrl } = await fakeWorker({
    reply: [202, { ok: true, pending: true, job_id: JOB }],
    polls: [[200, { state: "running" }], [404, { state: "unknown" }]],
  });
  t.after(() => server.close());

  const result = await callWorker(options(baseUrl));
  assert.equal(result.ok, false);
  assert.match(result.text, /restarted/);
});

test("a few failed polls are tolerated, many in a row give up", async (t) => {
  const flaky = await fakeWorker({
    reply: [202, { ok: true, pending: true, job_id: JOB }],
    polls: [[502, {}], [502, {}], [200, { state: "done", ok: true, text: "ok" }]],
  });
  t.after(() => flaky.server.close());
  assert.deepEqual(await callWorker(options(flaky.baseUrl)), { ok: true, text: "ok" });

  const down = await fakeWorker({ reply: [202, { ok: true, pending: true, job_id: JOB }], polls: [[502, {}]] });
  t.after(() => down.server.close());
  const result = await callWorker(options(down.baseUrl, { maxPollFailures: 3 }));
  assert.equal(result.ok, false);
  assert.match(result.text, /bot-worker unreachable: HTTP 502/);
  assert.equal(down.seen.polls, 3);
});

test("a job that never finishes stops at the total deadline", async (t) => {
  const { server, baseUrl } = await fakeWorker({
    reply: [202, { ok: true, pending: true, job_id: JOB }],
    polls: [[200, { state: "running" }]],
  });
  t.after(() => server.close());

  const result = await callWorker(options(baseUrl, { totalTimeoutMs: 50, pollIntervalMs: 5 }));
  assert.equal(result.ok, false);
  assert.match(result.text, /did not finish within/);
});

test("an unreachable worker and an invalid job id are reported", async () => {
  const gone = await callWorker(options("http://127.0.0.1:1", { requestTimeoutMs: 500 }));
  assert.equal(gone.ok, false);
  assert.match(gone.text, /^bot-worker unreachable: /);

  const { server, baseUrl } = await fakeWorker({ reply: [202, { ok: true, pending: true, job_id: "../../etc" }] });
  const bad = await callWorker(options(baseUrl));
  server.close();
  assert.equal(bad.ok, false);
  assert.match(bad.text, /invalid job id/);
});

test("a worker that predates job mode still works (answers 200 synchronously)", async (t) => {
  const { server, baseUrl } = await fakeWorker({ reply: [200, { ok: true, text: "old worker" }] });
  t.after(() => server.close());
  assert.deepEqual(await callWorker(options(baseUrl)), { ok: true, text: "old worker" });
});

// The reason this module exists, measured rather than assumed: Node's fetch drops a response that starts later
// than 300s even with a 630s AbortSignal. Takes 5+ minutes, so it is opt-in: RUN_SLOW=1 node --test
test("[slow] plain fetch dies at ~300s on a slow response, whatever the AbortSignal says", { skip: !process.env.RUN_SLOW, timeout: 400_000 }, async () => {
  const server = http.createServer((req, res) => setTimeout(() => res.end("{}"), 330_000));
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const started = Date.now();
  let cause;
  try {
    await fetch(`http://127.0.0.1:${server.address().port}`, { signal: AbortSignal.timeout(630_000) });
  } catch (err) {
    cause = err.cause?.code;
  }
  server.closeAllConnections();
  server.close();
  assert.equal(cause, "UND_ERR_HEADERS_TIMEOUT");
  assert.ok(Date.now() - started < 310_000);
});
