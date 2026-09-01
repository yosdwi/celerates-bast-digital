"use strict";

const fs = require("node:fs");

function readSecret(valueName, fileName, fallback = "") {
  const direct = String(process.env[valueName] || "").trim();
  const file = String(process.env[fileName] || "").trim();
  if (direct && file) throw new Error(`duplicate secret sources: ${valueName}`);
  if (direct) return direct;
  if (!file) return fallback;
  return fs.readFileSync(file, "utf8").trim();
}

function loadConfig() {
  return {
    host: process.env.META_WA_GATEWAY_HOST || "0.0.0.0",
    port: Number(process.env.META_WA_GATEWAY_PORT || 8090),
    graphVersion: String(process.env.META_GRAPH_VERSION || "").trim(),
    phoneNumberId: String(process.env.META_WA_PHONE_NUMBER_ID || "").trim(),
    businessPhone: String(process.env.META_WA_DISPLAY_PHONE_NUMBER || "").trim(),
    accessToken: readSecret("META_WA_ACCESS_TOKEN", "META_WA_ACCESS_TOKEN_FILE"),
    appSecret: readSecret("META_APP_SECRET", "META_APP_SECRET_FILE"),
    verifyToken: readSecret("META_WEBHOOK_VERIFY_TOKEN", "META_WEBHOOK_VERIFY_TOKEN_FILE"),
    bridgeToken: readSecret(
      "BOT_BRIDGE_TOKEN",
      "BOT_BRIDGE_TOKEN_FILE",
      readSecret("SYNC_INGEST_TOKEN", "SYNC_INGEST_TOKEN_FILE"),
    ),
    databaseDsn: readSecret("APP_DATABASE_DSN", "APP_DATABASE_DSN_FILE"),
    workerBaseUrl: String(process.env.BOT_WORKER_BASE_URL || "http://bot-worker:8091").replace(/\/$/, ""),
    dataDir: process.env.BOT_DATA_DIR || "/data",
    utilityTemplate: String(process.env.META_DEFAULT_UTILITY_TEMPLATE || "").trim(),
    templateLanguage: String(process.env.META_TEMPLATE_LANGUAGE || "id").trim(),
    graphBaseUrl: String(process.env.META_GRAPH_BASE_URL || "https://graph.facebook.com").replace(/\/$/, ""),
    requestTimeoutMs: Number(process.env.META_REQUEST_TIMEOUT_MS || 30000),
  };
}

function missingConfig(config) {
  const required = [
    ["META_GRAPH_VERSION", config.graphVersion],
    ["META_WA_PHONE_NUMBER_ID", config.phoneNumberId],
    ["META_WA_ACCESS_TOKEN", config.accessToken],
    ["META_APP_SECRET", config.appSecret],
    ["META_WEBHOOK_VERIFY_TOKEN", config.verifyToken],
    ["BOT_BRIDGE_TOKEN", config.bridgeToken],
    ["APP_DATABASE_DSN", config.databaseDsn],
  ];
  return required.filter(([, value]) => !value).map(([name]) => name);
}

module.exports = { loadConfig, missingConfig, readSecret };
