import type { AttentionItem, CommandCenterResponse, SourceFreshness } from "../api/types";

const DOMAIN_LABEL: Record<string, string> = {
  attendance: "Attendance",
  timesheet: "Timesheet",
  task: "Task",
  evidence: "Evidence",
};

export function domainLabel(domain: string): string {
  return DOMAIN_LABEL[domain] ?? domain;
}

export function readinessPercent(ready: number, total: number): string {
  if (total <= 0) return "—";
  return `${Math.round((ready / total) * 1000) / 10}%`;
}

export function primaryBlocker(item: AttentionItem): string {
  return item.blockers.length > 0 ? domainLabel(item.blockers[0].domain) : "Review";
}

export function totalIssues(item: AttentionItem): number {
  return item.blockers.reduce((sum, blocker) => sum + blocker.issues.length, 0);
}

export function deterministicInsight(data: CommandCenterResponse): string {
  if (data.attention.length === 0) {
    return "All active talents pass the current readiness rules.";
  }

  const talentCountByDomain = new Map<string, number>();
  for (const item of data.attention) {
    for (const domain of new Set(item.blockers.map((blocker) => blocker.domain))) {
      talentCountByDomain.set(domain, (talentCountByDomain.get(domain) ?? 0) + 1);
    }
  }
  const top = [...talentCountByDomain.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0];
  if (!top) {
    return `${data.attention.length} talents need PMO review.`;
  }
  return `${domainLabel(top[0])} is the main blocker · ${top[1]} talent${top[1] === 1 ? "" : "s"} affected.`;
}

export function sourceAge(source: SourceFreshness): string {
  if (source.age_seconds === null) return "Unknown";
  const seconds = Math.max(0, source.age_seconds);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
