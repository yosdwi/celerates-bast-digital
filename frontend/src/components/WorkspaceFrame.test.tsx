import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TalentOpsSession } from "../api/types";
import { PeriodControlProvider } from "../app/PeriodContext";
import WorkspaceFrame from "./WorkspaceFrame";

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

afterEach(() => cleanup());

describe("WorkspaceFrame period control", () => {
  it("shows the active month and requests a new global period", () => {
    const onChange = vi.fn();
    render(
      <PeriodControlProvider
        value={{
          period: { year: 2026, month: 8, label: "1-31 Agustus 2026" },
          pending: null,
          loading: false,
          error: null,
          onChange,
        }}
      >
        <WorkspaceFrame
          session={session}
          active="command-center"
          attentionCount={0}
          search=""
          onSearch={vi.fn()}
          onNavigate={vi.fn()}
          onAskAi={vi.fn()}
        >
          <div>Workspace body</div>
        </WorkspaceFrame>
      </PeriodControlProvider>,
    );

    const input = screen.getByLabelText("Reporting period");
    expect(input).toHaveValue("2026-08");

    fireEvent.change(input, { target: { value: "2026-07" } });
    expect(onChange).toHaveBeenCalledWith({ year: 2026, month: 7 });
  });

  it("shows the pending period and a global load error", () => {
    render(
      <PeriodControlProvider
        value={{
          period: { year: 2026, month: 8, label: "1-31 Agustus 2026" },
          pending: { year: 2026, month: 7 },
          loading: true,
          error: "Unable to load the selected period.",
          onChange: vi.fn(),
        }}
      >
        <WorkspaceFrame
          session={session}
          active="talents"
          attentionCount={1}
          search=""
          onSearch={vi.fn()}
          onNavigate={vi.fn()}
          onAskAi={vi.fn()}
        >
          <div>Workspace body</div>
        </WorkspaceFrame>
      </PeriodControlProvider>,
    );

    expect(screen.getByLabelText("Reporting period")).toHaveValue("2026-07");
    expect(screen.getByRole("status")).toHaveTextContent("Unable to load the selected period.");
  });
});
