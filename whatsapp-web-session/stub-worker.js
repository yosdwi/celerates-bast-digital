"use strict";

// Throwaway stand-in for bot-worker, used only by compose.prototype.yaml.
// Implements the same POST /internal/v1/reply contract (auth + shape) so
// the prototype exercises the real request/response path end-to-end
// without shelling out to the actual `digital-bast` CLI or touching any
// production data. Echoes back what it received, plus a couple of canned
// replies to exercise the interactive/file envelopes.

const http = require("node:http");
const fs = require("node:fs");
const crypto = require("node:crypto");

const PORT = Number(process.env.BOT_WORKER_PORT || 8091);
const HOST = process.env.BOT_WORKER_HOST || "0.0.0.0";
const TOKEN_FILE = process.env.BOT_BRIDGE_TOKEN_FILE || process.env.SYNC_INGEST_TOKEN_FILE || "/run/secrets/sync_ingest_token";

function configuredToken() {
  try {
    return fs.readFileSync(TOKEN_FILE, "utf8").trim();
  } catch {
    return "";
  }
}

function safeEqual(left, right) {
  const a = Buffer.from(String(left || ""));
  const b = Buffer.from(String(right || ""));
  if (a.length === 0 || a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

function replyFor(payload) {
  if (payload.kind === "evidence") {
    return { ok: true, text: `(stub) evidence diterima dari ${payload.jid}: ${payload.filePath}` };
  }
  const text = String(payload.text || "").trim();
  if (/^menu$/i.test(text)) {
    return {
      ok: true,
      text: JSON.stringify({
        kind: "interactive",
        text: "(stub) Pilih salah satu:",
        actions: [
          { id: "status", label: "Cek status" },
          { id: "help", label: "Bantuan" },
        ],
      }),
    };
  }
  return { ok: true, text: `(stub echo) kamu bilang: ${text}` };
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true }));
    return;
  }
  if (req.method === "POST" && req.url === "/internal/v1/reply") {
    if (!safeEqual(req.headers["x-bridge-token"], configuredToken())) {
      res.writeHead(403, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: false, text: "forbidden" }));
      return;
    }
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      let payload;
      try {
        payload = JSON.parse(body || "{}");
      } catch {
        res.writeHead(400, { "content-type": "application/json" });
        res.end(JSON.stringify({ ok: false, text: "invalid_json" }));
        return;
      }
      const result = replyFor(payload);
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify(result));
    });
    return;
  }
  res.writeHead(404, { "content-type": "text/plain" });
  res.end("not found");
});

server.listen(PORT, HOST, () => {
  console.log(`${new Date().toISOString()} stub-worker listening on http://${HOST}:${PORT}`);
});
