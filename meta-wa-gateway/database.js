"use strict";

const { createHash } = require("node:crypto");
const { Pool } = require("pg");

function payloadHash(payload) {
  return createHash("sha256").update(JSON.stringify(payload)).digest("hex");
}

class GatewayDatabase {
  constructor(dsn, pool = null) {
    this.pool = pool || new Pool({ connectionString: dsn, max: 4, connectionTimeoutMillis: 5000 });
  }

  async ready() {
    await this.pool.query("SELECT 1");
    return true;
  }

  async claimInbound(message) {
    const result = await this.pool.query(
      `INSERT INTO whatsapp_inbound_events
         (provider_message_id, wa_id, message_type, payload, status, attempts)
       VALUES ($1,$2,$3,$4::jsonb,'processing',1)
       ON CONFLICT (provider_message_id) DO UPDATE SET
         status = 'processing', attempts = whatsapp_inbound_events.attempts + 1,
         last_error = NULL, updated_at = now()
       WHERE whatsapp_inbound_events.attempts < 5
         AND (whatsapp_inbound_events.status IN ('queued', 'failed')
          OR (whatsapp_inbound_events.status = 'processing'
              AND whatsapp_inbound_events.updated_at < now() - interval '5 minutes'))
       RETURNING provider_message_id`,
      [message.id, message.waId, message.kind, JSON.stringify(message)],
    );
    return result.rowCount === 1;
  }

  async enqueueInbound(messages) {
    for (const message of messages) {
      await this.pool.query(
        `INSERT INTO whatsapp_inbound_events
           (provider_message_id, wa_id, message_type, payload, status, attempts)
         VALUES ($1,$2,$3,$4::jsonb,'queued',0)
         ON CONFLICT (provider_message_id) DO NOTHING`,
        [message.id, message.waId, message.kind, JSON.stringify(message)],
      );
    }
  }

  async pendingInbound(limit = 50) {
    const result = await this.pool.query(
      `SELECT payload FROM whatsapp_inbound_events
       WHERE attempts < 5
         AND (status IN ('queued', 'failed')
          OR (status='processing' AND updated_at < now() - interval '5 minutes'))
       ORDER BY received_at
       LIMIT $1`,
      [limit],
    );
    return result.rows.map((row) => row.payload);
  }

  async completeInbound(messageId) {
    await this.pool.query(
      "UPDATE whatsapp_inbound_events SET status='processed', processed_at=now(), updated_at=now() WHERE provider_message_id=$1",
      [messageId],
    );
  }

  async failInbound(messageId, error) {
    await this.pool.query(
      "UPDATE whatsapp_inbound_events SET status='failed', last_error=$2, updated_at=now() WHERE provider_message_id=$1",
      [messageId, String(error).slice(0, 500)],
    );
  }

  async recordStatus(event) {
    await this.pool.query(
      `INSERT INTO whatsapp_message_status_events
         (provider_message_id, status, recipient_wa_id, provider_timestamp, error_code, error_title)
       VALUES ($1,$2,$3,$4,$5,$6)
       ON CONFLICT (provider_message_id, status) DO NOTHING`,
      [event.messageId, event.status, event.recipientWaId || null, event.timestamp || null, event.errorCode, event.errorTitle],
    );
    const column = { delivered: "delivered_at", read: "read_at", failed: "failed_at" }[event.status];
    if (!column) return;
    await this.pool.query(
      `UPDATE talentops_followups SET ${column}=COALESCE(${column}, now()), delivery_error_code=COALESCE($2, delivery_error_code) WHERE provider_message_id=$1`,
      [event.messageId, event.errorCode],
    );
    await this.pool.query(
      `UPDATE workflow_notification_outbox SET ${column}=COALESCE(${column}, now()), delivery_error_code=COALESCE($2, delivery_error_code) WHERE provider_message_id=$1`,
      [event.messageId, event.errorCode],
    );
  }

  async reconcileStatuses() {
    const statement = (table) => `
      WITH lifecycle AS (
        SELECT provider_message_id,
               min(received_at) FILTER (WHERE status='delivered') AS delivered_at,
               min(received_at) FILTER (WHERE status='read') AS read_at,
               min(received_at) FILTER (WHERE status='failed') AS failed_at,
               max(error_code) FILTER (WHERE status='failed') AS error_code
        FROM whatsapp_message_status_events
        GROUP BY provider_message_id
      )
      UPDATE ${table} AS target SET
        delivered_at=COALESCE(target.delivered_at, lifecycle.delivered_at),
        read_at=COALESCE(target.read_at, lifecycle.read_at),
        failed_at=COALESCE(target.failed_at, lifecycle.failed_at),
        delivery_error_code=COALESCE(target.delivery_error_code, lifecycle.error_code)
      FROM lifecycle
      WHERE target.provider_message_id=lifecycle.provider_message_id`;
    await this.pool.query(statement("talentops_followups"));
    await this.pool.query(statement("workflow_notification_outbox"));
  }

  async claimOutbound(requestId, payload) {
    const hash = payloadHash(payload);
    const inserted = await this.pool.query(
      `INSERT INTO whatsapp_outbound_requests (request_id, payload_hash, status, attempts)
       VALUES ($1,$2,'pending',1)
       ON CONFLICT (request_id) DO NOTHING
       RETURNING request_id`,
      [requestId, hash],
    );
    if (inserted.rowCount === 1) return { action: "send", hash };
    const existing = await this.pool.query(
      "SELECT payload_hash, status, provider_message_id, error_code, updated_at FROM whatsapp_outbound_requests WHERE request_id=$1",
      [requestId],
    );
    const row = existing.rows[0];
    if (!row || row.payload_hash !== hash) return { action: "conflict" };
    if (row.status === "sent") return { action: "replay", providerMessageId: row.provider_message_id };
    if (row.status === "pending") {
      const reclaimed = await this.pool.query(
        `UPDATE whatsapp_outbound_requests SET attempts=attempts+1, updated_at=now()
         WHERE request_id=$1 AND status='pending' AND updated_at < now() - interval '5 minutes'
         RETURNING request_id`,
        [requestId],
      );
      return reclaimed.rowCount === 1 ? { action: "send", hash } : { action: "pending" };
    }
    const retried = await this.pool.query(
      `UPDATE whatsapp_outbound_requests SET status='pending', attempts=attempts+1,
         error_code=NULL, updated_at=now()
       WHERE request_id=$1 AND status='failed' RETURNING request_id`,
      [requestId],
    );
    return retried.rowCount === 1 ? { action: "send", hash } : { action: "pending" };
  }

  async completeOutbound(requestId, providerMessageId) {
    await this.pool.query(
      "UPDATE whatsapp_outbound_requests SET status='sent', provider_message_id=$2, sent_at=now(), updated_at=now() WHERE request_id=$1",
      [requestId, providerMessageId],
    );
  }

  async failOutbound(requestId, errorCode) {
    await this.pool.query(
      "UPDATE whatsapp_outbound_requests SET status='failed', error_code=$2, updated_at=now() WHERE request_id=$1",
      [requestId, String(errorCode || "send_failed").slice(0, 120)],
    );
  }

  async close() {
    await this.pool.end();
  }
}

module.exports = { GatewayDatabase, payloadHash };
