import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FollowUps } from "../hooks/useFollowUps";
import type { CaseDetail } from "../hooks/usePostSales";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const kase = {
  id: 4, case_code: "PSC-00004", status: "accepted", onboarding_status: "documents_pending", customer: "Anita Desai", project: "Habitat", unit_no: "1114",
  booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-11-17", agreed_price: 3_225_000, owner: null, sales_exec: null, created_at: "2026-11-17T05:00:00Z",
  kyc_done: 0, kyc_total: 4, returned_reason: null, clarification_reason: null, accepted_at: "2026-11-17T05:00:00Z", handover: [], profile: null, co_applicants: [],
  requirements: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: false, history: [],
} as unknown as CaseDetail;
const base: FollowUps = { items: [], outstanding: 328_950, demands: [{ id: 7, demand_no: "DMD-00007", stage_name: "Plinth" }], can_write: true };
const by = { id: 2, full_name: "Pooja Test", role: "postsales_exec" as const };

async function openTab() {
  await userEvent.click(await screen.findByRole("tab", { name: "Follow-ups" }));
  return screen.findByRole("tabpanel", { name: "Follow-ups" });
}

describe("follow-ups tab", () => {
  it("a promise needs the amount and date, and is sent with the demand", async () => {
    const { post } = mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/follow-ups": base },
      post: { "/post-sales/cases/4/follow-ups": base } });
    renderApp("/post-sales/4");
    const panel = await openTab();
    expect(panel).toHaveTextContent("Currently demanded and unpaid: ₹ 3,28,950");
    const form = within(panel).getByRole("form", { name: "Log a follow-up" });
    await userEvent.selectOptions(within(form).getByLabelText("Outcome"), "promised");
    expect(within(form).getByRole("button", { name: "Save follow-up" })).toBeDisabled();
    await userEvent.type(within(form).getByLabelText("Promised amount (₹)"), "100000");
    const when = new Date(Date.now() + 3 * 864e5).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
    await userEvent.type(within(form).getByLabelText("Promised by"), when);
    await userEvent.selectOptions(within(form).getByLabelText("About demand (optional)"), "7");
    await userEvent.type(within(form).getByLabelText("Note"), "Bank disbursal expected");
    await userEvent.click(within(form).getByRole("button", { name: "Save follow-up" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/follow-ups", expect.objectContaining({
      channel: "call", outcome: "promised", promise_amount: 100_000, promise_date: when, demand_id: 7, note: "Bank disbursal expected" })));
    expect(await screen.findByText(/Promise of ₹ 1,00,000 by/)).toBeInTheDocument();
  });

  it("shows each promise as open, kept or broken", async () => {
    const mk = (id: number, st: "open" | "kept" | "broken") => ({ id, channel: "call" as const, outcome: "promised" as const, note: null, demand_id: 7, demand_no: "DMD-00007",
      contacted_on: "2026-11-10", promise_date: "2026-11-20", promise_amount: 50_000 * id, promise_status: st, next_follow_up_on: null, by, created_at: "2026-11-10T05:00:00Z" });
    mockApi(makeUser("auditor"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/follow-ups": { ...base, can_write: false, items: [mk(1, "open"), mk(2, "kept"), mk(3, "broken")] } } });
    renderApp("/post-sales/4");
    const panel = await openTab();
    expect(within(panel).queryByRole("form", { name: "Log a follow-up" })).not.toBeInTheDocument();
    const list = within(panel).getByRole("list", { name: "Follow-up history" });
    for (const t of ["Promise open", "Promise kept", "Promise broken"]) expect(within(list).getByText(t)).toBeInTheDocument();
  });
});

describe("post-sales home", () => {
  it("lists follow-ups due, linking to the case", async () => {
    mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases": { items: [], total: 0, counts: {} },
      "/post-sales/follow-ups/due": [{ case_id: 4, case_code: "PSC-00004", customer: "Anita Desai", reason: "Promise broken", on: "2026-11-15", amount: 50_000 }] } });
    renderApp("/");
    const due = await screen.findByRole("region", { name: "Follow-ups due" });
    await within(due).findByText("Promise broken");
    expect(within(due).getByRole("link", { name: /Anita Desai/ })).toHaveAttribute("href", "/post-sales/4");
    expect(due).toHaveTextContent("₹ 50,000");
  });

  it("site staff don't get it (and it isn't requested)", async () => {
    const { get } = mockApi(makeUser("site"), { get: { "/post-sales/cases": { items: [], total: 0, counts: {} } } });
    renderApp("/");
    await screen.findByRole("region", { name: "Post-sales at a glance" });
    expect(screen.queryByRole("region", { name: "Follow-ups due" })).not.toBeInTheDocument();
    expect(get.mock.calls.map((c) => c[0])).not.toContain("/post-sales/follow-ups/due");
  });
});
