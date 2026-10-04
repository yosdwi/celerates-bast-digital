"use strict";

// Stateless HTTP wrapper around the `digital-bast` CLI. Holds no WhatsApp
// state at all -- wa-session is the only caller, over the internal Docker
// network -- so rebuilding/recreating this on every deploy (same as the
// combined bot-bridge did before the split) never touches the live session.

const http = require("node:http");
const path = require("node:path");
const crypto = require("node:crypto");
const fs = require("node:fs");
const { execFile } = require("node:child_process");

const DEFAULT_TOKEN_FILE = "/run/secrets/sync_ingest_token";
const ROOT = path.resolve(__dirname, "..");
const CLI = (process.env.BAST_CLI || "digital-bast").split(" ").filter(Boolean);
const PYTHON = process.env.BAST_PYTHON || "python";
// 30 min. A full developer BAST renders 245-430s and a dense IoT one up to ~660s (Oct 2026), the renderer runs one
// render at a time so a request can also queue behind another, and the renderer call itself is capped at 20 min
// (src/digital_bast/infrastructure/pdf_export.py). 600s killed the CLI mid-render; this must stay above 1200s.
const CLI_TIMEOUT_MS = Number(process.env.BAST_CLI_TIMEOUT_MS || 1_800_000);
// A request that has not finished after this long is handed back as a job (HTTP 202) instead of holding the
// connection open: wa-session's fetch drops any response that takes more than 300s to start (undici's default
// headers timeout), which is what produced "proses gagal saat menjalankan perintah" on every export > 5 min.
const INLINE_WAIT_MS = Number(process.env.BAST_INLINE_WAIT_MS || 20_000);
const JOB_TTL_MS = 60 * 60 * 1000;
const MAX_FINISHED_JOBS = 50;
const PORT = Number(process.env.BOT_WORKER_PORT || 8091);
const HOST = process.env.BOT_WORKER_HOST || "0.0.0.0";
const MAX_BODY_BYTES = 16 * 1024;

function safeEqual(left, right) {
  const a = Buffer.from(String(left || ""));
  const b = Buffer.from(String(right || ""));
  if (a.length === 0 || a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

function configuredToken() {
  const tokenFile =
    process.env.BOT_BRIDGE_TOKEN_FILE || process.env.SYNC_INGEST_TOKEN_FILE || DEFAULT_TOKEN_FILE;
  try {
    return fs.readFileSync(tokenFile, "utf8").trim();
  } catch {
    return "";
  }
}

function optionValue(args, name) {
  const index = args.indexOf(name);
  if (index < 0 || index + 1 >= args.length) return null;
  return args[index + 1];
}

// The transport contract stays unchanged; only the Python entrypoint differs
// by channel. DM uses the Talent workspace-aware router, while group traffic
// uses the PMO read-only natural-query router. Explicit export/generate/system
// commands are delegated back to the legacy CLI by group_entry.py.
function executionFor(args) {
  if (args[0] === "bot-evidence") {
    return {
      command: PYTHON,
      args: ["-m", "digital_bast.bot.dm_workflow", "evidence", ...args.slice(1)],
    };
  }
  if (args[0] === "bot-reply" && optionValue(args, "--channel") === "dm") {
    const text = optionValue(args, "--text");
    const jid = optionValue(args, "--jid");
    const messageAt = optionValue(args, "--message-at");
    if (text !== null && jid) {
      if (messageAt) {
        return {
          command: PYTHON,
          args: [
            "-m",
            "digital_bast.bot.dm_message_entry",
            "reply",
            "--text",
            text,
            "--jid",
            jid,
            "--message-at",
            messageAt,
          ],
        };
      }
      return {
        command: PYTHON,
        args: ["-m", "digital_bast.bot.dm_entry", "reply", "--text", text, "--jid", jid],
      };
    }
  }
  if (args[0] === "bot-reply") {
    const text = optionValue(args, "--text");
    if (text !== null) {
      return {
        command: PYTHON,
        args: ["-m", "digital_bast.bot.group_entry", "reply", "--text", text],
      };
    }
  }
  return { command: CLI[0], args: [...CLI.slice(1), ...args] };
}

function runCli(args) {
  const execution = executionFor(args);
  return new Promise((resolve) => {
    execFile(
      execution.command,
      execution.args,
      { cwd: ROOT, timeout: CLI_TIMEOUT_MS, maxBuffer: 8 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          resolve({ ok: false, text: (stderr || stdout || String(error)).trim() });
          return;
        }
        resolve({ ok: true, text: stdout.trim() });
      },
    );
  });
}

// Pure mapping from wa-session's request body to CLI arguments -- kept
// separate from runCli so it's testable without spawning a subprocess.
function cliArgsFor(payload) {
  if (payload && payload.kind === "evidence") {
    const { jid, filePath, caption } = payload;
    if (typeof jid !== "string" || !jid || typeof filePath !== "string" || !filePath) return null;
    return ["bot-evidence", "--jid", jid, "--file", filePath, "--caption", String(caption || "")];
  }
  if (payload && payload.kind === "text") {
    const { text, jid, channel, message_at: messageAt } = payload;
    if (typeof text !== "string") return null;
    const args = ["bot-reply", "--text", text];
    if (jid && channel) {
      args.push("--jid", jid, "--channel", channel);
      if (typeof messageAt === "string" && messageAt.trim()) {
        args.push("--message-at", messageAt.trim());
      }
    }
    return args;
  }
  return null;
}

// In-memory on purpose: the worker is stateless by design (see the header comment). A job lost to a worker
// restart is reported as such to the caller, who can simply ask again (a finished render is cached on disk).
const jobs = new Map();

function pruneJobs(now = Date.now()) {
  const finished = [];
  for (const [id, job] of jobs) {
    if (job.state !== "done") continue;
    if (now - job.finishedAt > JOB_TTL_MS) jobs.delete(id);
    else finished.push([id, job]);
  }
  if (finished.length <= MAX_FINISHED_JOBS) return;
  finished.sort((a, b) => a[1].finishedAt - b[1].finishedAt);
  for (const [id] of finished.slice(0, finished.length - MAX_FINISHED_JOBS)) jobs.delete(id);
}

function startJob(running) {
  pruneJobs();
  const id = crypto.randomUUID();
  const job = { state: "running", startedAt: Date.now(), finishedAt: 0, result: null };
  jobs.set(id, job);
  running.then((result) => {
    job.state = "done";
    job.finishedAt = Date.now();
    job.result = result;
  });
  return id;
}

function jobStatus(id) {
  pruneJobs();
  const job = jobs.get(id);
  if (!job) return null;
  return job.state === "done" ? { state: "done", ok: job.result.ok, text: job.result.text } : { state: "running" };
}

function authorized(request) {
  const expected = configuredToken();
  return Boolean(expected) && safeEqual(request.headers["x-bridge-token"], expected);
}

function readJsonBody(request) {
  return new Promise((resolve, reject) => {
    let body = "";
    request.on("data", (chunk) => {
      body += chunk;
      if (body.length > MAX_BODY_BYTES) {
        reject(new Error("body_too_large"));
        request.destroy();
      }
    });
    request.on("end", () => {
      try {
        resolve(JSON.parse(body || "{}"));
      } catch {
        reject(new Error("invalid_json"));
      }
    });
    request.on("error", reject);
  });
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, `http://${request.headers.host || "localhost"}`);

  if (request.method === "GET" && url.pathname === "/health") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ ok: true }));
    return;
  }

  const jobMatch = /^\/internal\/v1\/jobs\/([0-9a-f-]{36})$/.exec(url.pathname);
  if (request.method === "GET" && jobMatch) {
    if (!authorized(request)) {
      response.writeHead(403, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: false, text: "forbidden" }));
      return;
    }
    const status = jobStatus(jobMatch[1]);
    response.writeHead(status ? 200 : 404, { "content-type": "application/json" });
    response.end(JSON.stringify(status ?? { state: "unknown" }));
    return;
  }

  if (request.method === "POST" && url.pathname === "/internal/v1/reply") {
    if (!authorized(request)) {
      response.writeHead(403, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: false, text: "forbidden" }));
      return;
    }
    let payload;
    try {
      payload = await readJsonBody(request);
    } catch (error) {
      response.writeHead(400, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: false, text: String(error.message || error) }));
      return;
    }
    const args = cliArgsFor(payload);
    if (!args) {
      response.writeHead(422, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: false, text: "invalid_reply_request" }));
      return;
    }
    const running = runCli(args);
    // `async: true` (sent by the current wa-session) lets a slow command become a job; a caller that does not
    // send it keeps the old behaviour, so the bridge and the worker can be deployed in either order.
    let first;
    if (payload.async === true) {
      let timer;
      first = await Promise.race([running, new Promise((resolve) => (timer = setTimeout(resolve, INLINE_WAIT_MS, null)))]);
      clearTimeout(timer);
    } else {
      first = await running;
    }
    if (first === null) {
      response.writeHead(202, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: true, pending: true, job_id: startJob(running) }));
      return;
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(first));
    return;
  }

  response.writeHead(404, { "content-type": "text/plain" });
  response.end("not found");
});

if (require.main === module) {
  server.listen(PORT, HOST, () => {
    console.log(`${new Date().toISOString()} bot-worker listening on http://${HOST}:${PORT}`);
  });
}

module.exports = { safeEqual, configuredToken, cliArgsFor, executionFor, runCli, server, startJob, jobStatus, pruneJobs, jobs };
