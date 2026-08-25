import { describe, expect, it } from "vitest";
import type { CommandCenterResponse } from "../api/types";
import { deterministicInsight, readinessPercent, sourceAge } from "./insights";

function fixture(): CommandCenterResponse {
  return {
    period: { year: 2026, month: 8, start: "2026-08-01", end: "2026-08-31", label: "1-31 Agustus 2026" },
    summary: { active_talents: 2, bast_ready: 1, need_attention: 1, open_tasks: 1, evidence_ready: 1 },
    attention: [
      {
        employee_id: "e-1",
        nrp: "JIMT00001",
        name: "Example Talent",
        role: "Developer",
        overall_state: "incomplete",
        blockers: [
          { domain: "evidence", state: "incomplete", issues: ["Task evidence missing"] },
          { domain: "timesheet", state: "needs_review", issues: ["Timesheet review"] },
        ],
      },
    ],
    readiness: [],
    teams: [],
    delivery: { total_tasks: 2, closed_tasks: 1, non_closed_tasks: 1, status_counts: [{ status: "Closed", count: 1 }] },
    sources: [],
  };
}

describe("TalentOps deterministic UI derivations", () => {
  it("calculates readiness ratios from returned counts", () => {
    expect(readinessPercent(1, 2)).toBe("50%");
    expect(readinessPercent(0, 0)).toBe("—");
  });

  it("builds the insight from real blocker domains", () => {
    expect(deterministicInsight(fixture())).toContain("Evidence");
  });

  it("keeps unseen source freshness neutral", () => {
    expect(sourceAge({ source_key: "redmine", label: "Redmine", last_success_at: null, age_seconds: null })).toBe("Unknown");
  });
});
