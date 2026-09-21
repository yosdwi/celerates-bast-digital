import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import type { TalentOpsSession } from "../api/types";
import WhatsAppDirectorySettings from "./WhatsAppDirectorySettings";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));

const session: TalentOpsSession = {
  user: { name: "Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

const directory = {
  ready: true,
  connection: "connected",
  discovered_at: "2026-09-19T14:00:00Z",
  groups: [
    {
      jid: "120363000000000000@g.us",
      subject: "Payroll Closing",
      member_count: 2,
      participants: [
        {
          jid: "628111@c.us",
          display_name: "Andi WA",
          is_admin: true,
          is_super_admin: false,
          employee_id: "EMP-1",
          nrp: "10001",
          full_name: "Andi",
        },
        {
          jid: "628222@lid",
          display_name: "Budi WA",
          is_admin: false,
          is_super_admin: false,
          employee_id: null,
          nrp: null,
          full_name: null,
        },
      ],
    },
  ],
  talents: [
    {
      employee_id: "EMP-1",
      nrp: "10001",
      full_name: "Andi",
      role: "Developer",
      wa_jid: "628111@c.us",
      bound_at: "2026-09-19T14:00:00Z",
      discovered_in_groups: true,
    },
    {
      employee_id: "EMP-2",
      nrp: "10002",
      full_name: "Budi",
      role: "IoT Operations",
      wa_jid: null,
      bound_at: null,
      discovered_in_groups: false,
    },
  ],
};

const closingGroup = {
  scope_key: "default",
  group_jid: "120363000000000000@g.us",
  bridge_ready: true,
  verified: true,
  group_subject: "Payroll Closing",
};

const apiFetchMock = vi.mocked(apiFetch);

afterEach(() => cleanup());

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async (path, init) => {
    if (path === "/api/talentops/v1/whatsapp-directory" && !init) return directory;
    if (path.endsWith("/closing-group") && !init) return closingGroup;
    if (path.endsWith("/mappings/EMP-2") && init?.method === "PUT") {
      return { outcome: "bound", employee_id: "EMP-2", wa_jid: "628222@lid" };
    }
    throw new Error(`Unexpected request: ${path}`);
  });
});

describe("WhatsAppDirectorySettings", () => {
  it("shows live groups and exact mapped/unmapped Talent identities", async () => {
    render(<WhatsAppDirectorySettings session={session} />);

    const groupSummary = await screen.findByText("Payroll Closing");
    expect(groupSummary).toBeInTheDocument();
    // The Talent list further down the page also shows "Andi" for the same
    // mapped employee, so scope to this group's own card. Andi is already
    // mapped to a known Talent (full_name "Andi"), so the row shows that
    // authoritative name, not the raw WhatsApp display_name "Andi WA" --
    // Budi is unmapped (full_name null) and still shows the raw WhatsApp
    // display_name.
    const groupCard = groupSummary.closest("details") as HTMLElement;
    expect(within(groupCard).getByText("Andi")).toBeInTheDocument();
    expect(within(groupCard).getByText("Budi WA")).toBeInTheDocument();
    expect(screen.getByText("Mapped · 10001")).toBeInTheDocument();
    expect(screen.getByText("Unmapped")).toBeInTheDocument();
    expect(screen.getByText("Verified · Payroll Closing")).toBeInTheDocument();
  });

  it("binds an unmapped discovered contact with CSRF and exact JID", async () => {
    render(<WhatsAppDirectorySettings session={session} />);
    const selector = await screen.findByLabelText("WhatsApp identity for Budi");

    fireEvent.change(selector, { target: { value: "628222@lid" } });
    fireEvent.click(screen.getByRole("button", { name: "Bind" }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        "/api/talentops/v1/whatsapp-directory/mappings/EMP-2",
        expect.objectContaining({
          method: "PUT",
          headers: { "X-CSRF-Token": "csrf-test" },
          body: JSON.stringify({ wa_jid: "628222@lid" }),
        }),
      );
    });
  });
});
