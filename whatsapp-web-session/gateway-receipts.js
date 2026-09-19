"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const STORE_VERSION = 1;
const DEFAULT_MAX_RECEIPTS = 2048;

function payloadFingerprint(jid, text) {
  return crypto.createHash("sha256").update(`${jid}\0${text}`, "utf8").digest("hex");
}

function unknownResult() {
  return { status: "unavailable", error: "delivery_outcome_unknown" };
}

class DurableOutboundReceiptStore {
  constructor({ filePath, maxReceipts = DEFAULT_MAX_RECEIPTS, logf = () => {} }) {
    this.filePath = filePath;
    this.maxReceipts = Math.max(1, Number(maxReceipts) || DEFAULT_MAX_RECEIPTS);
    this.logf = logf;
    this.records = new Map();
    this.inFlight = new Map();
    this.loadError = "";
    this._load();
  }

  _load() {
    let raw;
    try {
      raw = fs.readFileSync(this.filePath, "utf8");
    } catch (err) {
      if (err && err.code === "ENOENT") return;
      this.loadError = `receipt_store_read_failed:${err.message}`;
      this.logf(this.loadError);
      return;
    }

    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      this.loadError = `receipt_store_corrupt:${err.message}`;
      this.logf(this.loadError);
      return;
    }
    if (!parsed || parsed.version !== STORE_VERSION || !Array.isArray(parsed.receipts)) {
      this.loadError = "receipt_store_invalid_version";
      this.logf(this.loadError);
      return;
    }

    let reconciled = false;
    for (const item of parsed.receipts) {
      if (
        !item ||
        typeof item.request_id !== "string" ||
        typeof item.fingerprint !== "string" ||
        typeof item.state !== "string"
      ) {
        continue;
      }
      const record = { ...item };
      if (record.state === "accepted") {
        record.state = "unknown";
        record.result = unknownResult();
        record.updated_at = new Date().toISOString();
        reconciled = true;
      }
      if (record.state !== "sent" && record.state !== "unknown") continue;
      this.records.set(record.request_id, record);
    }
    this._trim();
    if (reconciled) this._persist();
  }

  _trim() {
    if (this.records.size <= this.maxReceipts) return;
    const ordered = [...this.records.values()].sort((left, right) =>
      String(left.updated_at || "").localeCompare(String(right.updated_at || "")),
    );
    for (const record of ordered.slice(0, ordered.length - this.maxReceipts)) {
      this.records.delete(record.request_id);
    }
  }

  _serialize(extra = null) {
    const receipts = [...this.records.values()];
    if (extra) receipts.push(extra);
    receipts.sort((left, right) =>
      String(left.updated_at || "").localeCompare(String(right.updated_at || "")),
    );
    return {
      version: STORE_VERSION,
      receipts: receipts.slice(-this.maxReceipts),
    };
  }

  _persist(extra = null) {
    const dir = path.dirname(this.filePath);
    fs.mkdirSync(dir, { recursive: true, mode: 0o750 });
    const temporary = `${this.filePath}.tmp-${process.pid}-${crypto.randomBytes(4).toString("hex")}`;
    const payload = `${JSON.stringify(this._serialize(extra))}\n`;
    fs.writeFileSync(temporary, payload, { mode: 0o640 });
    fs.renameSync(temporary, this.filePath);
  }

  snapshot() {
    let sent = 0;
    let unknown = 0;
    for (const record of this.records.values()) {
      if (record.state === "sent") sent += 1;
      if (record.state === "unknown") unknown += 1;
    }
    return {
      healthy: this.loadError === "",
      error: this.loadError || null,
      retained: this.records.size,
      sent,
      unknown,
      in_flight: this.inFlight.size,
      max_receipts: this.maxReceipts,
    };
  }

  async run(requestId, jid, text, sendFn) {
    const fingerprint = payloadFingerprint(jid, text);
    const completed = this.records.get(requestId);
    if (completed) {
      if (completed.fingerprint !== fingerprint) return { conflict: true };
      return completed.result;
    }
    if (this.loadError) {
      return { status: "unavailable", error: "receipt_store_unhealthy" };
    }

    const pending = this.inFlight.get(requestId);
    if (pending) {
      if (pending.fingerprint !== fingerprint) return { conflict: true };
      return pending.promise;
    }

    const accepted = {
      request_id: requestId,
      fingerprint,
      state: "accepted",
      result: null,
      updated_at: new Date().toISOString(),
    };
    this._persist(accepted);

    const promise = (async () => {
      let result;
      try {
        result = await sendFn();
      } catch (err) {
        this.logf(`outbound request ${requestId} threw after acceptance: ${err.message}`);
        result = unknownResult();
      }

      const finalResult = result && result.status === "sent" ? result : unknownResult();
      const record = {
        request_id: requestId,
        fingerprint,
        state: finalResult.status === "sent" ? "sent" : "unknown",
        result: finalResult,
        updated_at: new Date().toISOString(),
      };
      this.records.set(requestId, record);
      this._trim();
      this._persist();
      this.inFlight.delete(requestId);
      return finalResult;
    })();

    this.inFlight.set(requestId, { fingerprint, promise });
    return promise;
  }
}

module.exports = {
  DurableOutboundReceiptStore,
  payloadFingerprint,
};
