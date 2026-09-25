"use strict";

// Ported from whatsmeow-session/main.go's runtimeState + state_guard.go.
// Same "operator action required" latch: after a permanent logout/ban, we
// persist a marker file and refuse to auto-start a new QR/pairing cycle
// until an operator explicitly hits /pair. This is the guard the migration
// doc calls out by name -- don't let a real failure turn into a silent
// pairing-retry loop.

const fs = require("node:fs");
const path = require("node:path");

const MAX_LOGS = 200;

class RuntimeState {
  constructor(authDir) {
    this.connection = "starting";
    this.me = "";
    this.qrDataUrl = "";
    this.pairingCode = "";
    this.groups = [];
    this.logs = [];
    this.connectionChangedAt = new Date();
    this.operatorActionRequired = false;
    this.operatorReason = "";
    this.markerPath = path.join(authDir, "operator-action-required.json");
    this._loadMarker();
  }

  _loadMarker() {
    try {
      const raw = fs.readFileSync(this.markerPath, "utf8");
      const marker = JSON.parse(raw);
      this.connection = "pairing-required";
      this.connectionChangedAt = new Date();
      this.operatorActionRequired = true;
      this.operatorReason = [marker.connection, marker.reason].filter(Boolean).join(": ");
    } catch {
      // No marker: normal first start or a clean prior shutdown.
    }
  }

  requireOperatorAction(connection, reason) {
    const marker = { connection, reason, created_at: new Date().toISOString() };
    try {
      fs.mkdirSync(path.dirname(this.markerPath), { recursive: true, mode: 0o750 });
      fs.writeFileSync(this.markerPath, JSON.stringify(marker, null, 2), { mode: 0o640 });
    } catch (err) {
      this.logf(`failed to persist operator-action marker: ${err.message}`);
    }
    this.connection = "pairing-required";
    this.connectionChangedAt = new Date();
    this.operatorActionRequired = true;
    this.operatorReason = [connection, reason].filter(Boolean).join(": ");
  }

  clearOperatorAction() {
    try {
      fs.rmSync(this.markerPath, { force: true });
    } catch (err) {
      this.logf(`failed to clear operator-action marker: ${err.message}`);
    }
    this.operatorActionRequired = false;
    this.operatorReason = "";
  }

  setConnection(value) {
    this.connection = value;
    this.connectionChangedAt = new Date();
  }

  logf(line) {
    const entry = `${new Date().toISOString()} ${line}`;
    console.log(entry);
    this.logs.unshift(entry);
    if (this.logs.length > MAX_LOGS) this.logs.length = MAX_LOGS;
  }

  snapshot() {
    return {
      connection: this.connection,
      me: this.me,
      qrDataUrl: this.qrDataUrl,
      pairingCode: this.pairingCode,
      groups: this.groups,
      logs: this.logs,
      operatorActionRequired: this.operatorActionRequired,
      operatorReason: this.operatorReason,
      connectionChangedAt: this.connectionChangedAt,
    };
  }
}

module.exports = { RuntimeState };
