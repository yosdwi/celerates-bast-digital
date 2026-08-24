import type { CheckState } from "../api/types";

export function statusLabel(state: CheckState): string {
  if (state === "complete") return "Ready";
  if (state === "needs_review") return "Review";
  return "Blocked";
}

export function StatusBadge({ state, compact = false }: { state: CheckState; compact?: boolean }) {
  return (
    <span className={`status-badge status-${state}${compact ? " status-compact" : ""}`}>
      <span className="status-dot" />
      {statusLabel(state)}
    </span>
  );
}
