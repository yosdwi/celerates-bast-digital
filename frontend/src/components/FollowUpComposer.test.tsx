import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getFollowUpDraft, sendFollowUp } from "../api/talentops";
import type { FollowUpDraft, FollowUpSendResponse, TalentOpsSession } from "../api/types";
import FollowUpComposer from "./FollowUpComposer";

vi.mock("../api/talentops", () => ({
  getFollowUpDraft: vi.fn(),
  sendFollowUp: vi.fn(),
}));

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

const period = { year: 2026, month: 8, label: "1-31 Agustus 2026" };

const linkedDraft: FollowUpDraft = {
  nrp: "JIMT24002",
  name: "Yoses Dwi Maheswara",
  whatsapp_bound: true,
  message: "Halo Yoses, evidence task A masih perlu dilengkapi.",
  source: "ai",
  last_follow_up: null,
};

const sent: FollowUpSendResponse = {
  status: "sent",
  delivery_id: "delivery-1",
  provider_message_id: "wa-1",
  sent_at: "2026-08-25T05:00:00Z",
  error_code: null,
  duplicate: false,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FollowUpComposer", () => {
  it("shows identity binding precisely and sends only after an explicit click", async () => {
    vi.mocked(getFollowUpDraft).mockResolvedValue(linkedDraft);
    vi.mocked(sendFollowUp).mockResolvedValue(sent);

    render(
      <FollowUpComposer
        session={session}
        nrp="JIMT24002"
        name="Yoses Dwi Maheswara"
        period={period}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText("Identity linked")).toBeInTheDocument();
    expect(screen.queryByText("Connected")).not.toBeInTheDocument();
    expect(sendFollowUp).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Send WhatsApp" }));

    await waitFor(() => expect(sendFollowUp).toHaveBeenCalledTimes(1));
    expect(sendFollowUp).toHaveBeenCalledWith(
      "csrf-test",
      "JIMT24002",
      period,
      linkedDraft.message,
      "ai",
      expect.any(String),
    );
    expect(await screen.findByText("WhatsApp follow-up sent.")).toBeInTheDocument();
  });

  it("keeps send disabled when the talent has no WhatsApp identity binding", async () => {
    vi.mocked(getFollowUpDraft).mockResolvedValue({
      ...linkedDraft,
      whatsapp_bound: false,
      source: "deterministic",
    });

    render(
      <FollowUpComposer
        session={session}
        nrp="JIMT24002"
        name="Yoses Dwi Maheswara"
        period={period}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText("Not linked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send WhatsApp" })).toBeDisabled();
    expect(sendFollowUp).not.toHaveBeenCalled();
  });
});
