import { apiFetch } from "./client";

const BASE = "/api/talentops/v1/system/whatsapp";

export interface WhatsAppOperationsStatus {
  alive: boolean;
  ready: boolean;
  connection: string;
  me: string;
  qr_data_url: string | null;
  pairing_code: string | null;
  operator_action_required: boolean;
  operator_reason: string | null;
  connection_changed_at: string | null;
  recovery_state: string;
  recovery_reason: string | null;
  recovery_paused: boolean;
  last_probe_at: string | null;
  last_ready_at: string | null;
  last_ack_at: string | null;
  cooldown_until: string | null;
  recovery_attempts: number;
  recovery_max_attempts: number;
  recovery_policy_version: number;
  applied_recovery_policy_version: number;
  owner_acquired: boolean;
  owner_conflict_id: string | null;
  owner_conflict_heartbeat_at: string | null;
  storage_healthy: boolean;
  storage_reasons: string[];
  free_bytes: number | null;
  free_inodes: number | null;
  receipt_store_healthy: boolean;
  receipt_store_error: string | null;
  receipt_sent: number;
  receipt_unknown: number;
  receipt_in_flight: number;
  transport: string;
}

export interface WhatsAppOperationsControlResult {
  accepted: boolean;
  reason: string;
}

export function unavailableWhatsAppOperations(): WhatsAppOperationsStatus {
  return {
    alive: false,
    ready: false,
    connection: "unavailable",
    me: "",
    qr_data_url: null,
    pairing_code: null,
    operator_action_required: false,
    operator_reason: null,
    connection_changed_at: null,
    recovery_state: "unavailable",
    recovery_reason: "status_unavailable",
    recovery_paused: false,
    last_probe_at: null,
    last_ready_at: null,
    last_ack_at: null,
    cooldown_until: null,
    recovery_attempts: 0,
    recovery_max_attempts: 0,
    recovery_policy_version: 0,
    applied_recovery_policy_version: 0,
    owner_acquired: false,
    owner_conflict_id: null,
    owner_conflict_heartbeat_at: null,
    storage_healthy: false,
    storage_reasons: ["status_unavailable"],
    free_bytes: null,
    free_inodes: null,
    receipt_store_healthy: false,
    receipt_store_error: "status_unavailable",
    receipt_sent: 0,
    receipt_unknown: 0,
    receipt_in_flight: 0,
    transport: "whatsapp-web.js",
  };
}

export function getWhatsAppOperations(): Promise<WhatsAppOperationsStatus> {
  return apiFetch<WhatsAppOperationsStatus>(`${BASE}/operations`);
}

export function controlWhatsAppRecovery(
  csrfToken: string,
  action: "pause" | "resume" | "reconnect",
): Promise<WhatsAppOperationsControlResult> {
  return apiFetch<WhatsAppOperationsControlResult>(`${BASE}/recovery/${action}`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  });
}

export function startControlledWhatsAppPairing(
  csrfToken: string,
): Promise<WhatsAppOperationsControlResult> {
  return apiFetch<WhatsAppOperationsControlResult>(`${BASE}/pair`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  });
}
