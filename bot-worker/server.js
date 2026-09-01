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
const CLI_TIMEOUT_MS = Number(process.env.BAST_CLI_TIMEOUT_MS || 180000);
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
    if (text !== null && jid) {
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
    const { text, jid, channel } = payload;
    if (typeof text !== "string") return null;
    const args = ["bot-reply", "--text", text];
    if (jid && channel) args.push("--jid", jid, "--channel", channel);
    return args;
  }
  return null;
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

  if (request.method === "POST" && url.pathname === "/internal/v1/reply") {
    const expected = configuredToken();
    const supplied = request.headers["x-bridge-token"];
    if (!expected || !safeEqual(supplied, expected)) {
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
    const result = await runCli(args);
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(result));
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

module.exports = { safeEqual, configuredToken, cliArgsFor, executionFor, runCli, server };
