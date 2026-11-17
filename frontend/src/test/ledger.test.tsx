import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CaseDetail } from "../hooks/usePostSales";
import type { Ledger } from "../hooks/useLedger";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const kase = {
  id: 4, case_code: "PSC-00004", status: "accepted", onboarding_status: "documents_pending", customer: "Anita Desai", project: "Habitat", unit_no: "1114",
  booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-11-17", agreed_price: 3_225_000, owner: null, sales_exec: null, created_at: "2026-11-17T05:00:00Z",
  kyc_done: 0, kyc_total: 4, returned_reason: null, clarification_reason: null, accepted_at: "2026-11-17T05:00:00Z", handover: [], profile: null, co_applicants: [],
  requirements: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: false, history: [],
} as unknown as CaseDetail;
const labels = { base_price: "Base price (agreed)", gst: "GST", stamp_duty: "Stamp duty", parking: "Parking", discount: "Discount" };
const ledger: Ledger = {
  exists: true, status: "draft", version: 1, gst_pct: 1, loan_sanctioned: 2_500_000, lender: "HDFC Bank", loan_reference: null, note: null,
  submitted_by: null, submitted_at: null, approved_by: null, approved_at: null, can_edit: true, can_approve: false, head_labels: labels, problems: [],
  charges: [{ head: "base_price", label: "Base price (agreed)", amount: 3_225_000 }, { head: "gst", label: "GST", amount: 32_250 }, { head: "stamp_duty", label: "Stamp duty", amount: 225_800 }],
  schedule: [{ seq: 1, name: "Booking", amount: 322_500, gst: 3_225, trigger_type: "on_booking", due_date: "2026-11-17", milestone: null, is_due: true },
    { seq: 2, name: "Plinth", amount: 2_902_500, gst: 29_025, trigger_type: "on_milestone", due_date: null, milestone: "Plinth", is_due: false }],
  totals: { agreement_value: 3_225_000, gst: 32_250, statutory: 225_800, other: 0, total_payable: 3_483_050, schedule_amount: 3_225_000, schedule_gst: 32_250 },
  balances: { received: 322_500, received_own: 322_500, loan_disbursed: 0, total_outstanding: 3_160_550, currently_demanded: 3_225, overdue: 0,
    own_contribution_required: 660_550, loan_not_disbursed: 2_500_000, under_dispute: 0, other_charges: 225_800, unapplied: 0, pending_confirmation: 0 },
};

async function openLedger() {
  await userEvent.click(await screen.findByRole("tab", { name: "Ledger" }));
  return screen.findByRole("tabpanel", { name: "Ledger" });
}

describe("ledger tab", () => {
  it("shows the seven balances, charges by group and the schedule", async () => {
    mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/ledger": ledger } });
    renderApp("/post-sales/4");
    const panel = await openLedger();
    const balances = within(panel).getByRole("region", { name: "Balances" });
    for (const [label, value] of [["Total outstanding", "₹ 31,60,550"], ["Currently demanded", "₹ 3,225"], ["Own contribution still required", "₹ 6,60,550"],
      ["Loan not yet disbursed", "₹ 25,00,000"], ["Other charges (outside the plan)", "₹ 2,25,800"]]) {
      expect(within(balances).getByText(label).nextSibling).toHaveTextContent(value);
    }
    const charges = within(panel).getByRole("table", { name: "Charges" });
    expect(within(charges).getByRole("rowgroup", { name: "Agreement value" })).toHaveTextContent("Base price (agreed)₹ 32,25,000");
    expect(charges).toHaveTextContent("Total payable₹ 34,83,050");
    const schedule = within(panel).getByRole("table", { name: "Payment schedule" });
    expect(within(schedule).getByRole("row", { name: /Booking/ })).toHaveTextContent("Due");
    expect(within(schedule).getByRole("row", { name: /Plinth/ })).toHaveTextContent("Milestone: Plinth");
  });

  it("problems are listed and block submitting", async () => {
    mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/ledger": { ...ledger, problems: ["The payment schedule is empty"] } } });
    renderApp("/post-sales/4");
    const panel = await openLedger();
    expect(within(panel).getByText("The payment schedule is empty")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Submit for approval" })).toBeDisabled();
  });

  it("finance generates a ledger when there is none", async () => {
    const { post } = mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/ledger": { exists: false, can_edit: true, head_labels: labels } },
      post: { "/post-sales/cases/4/ledger/generate": ledger } });
    renderApp("/post-sales/4");
    const panel = await openLedger();
    await userEvent.click(within(panel).getByRole("button", { name: "Generate ledger" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/ledger/generate", undefined));
    expect(await screen.findByText("Ledger generated from the cost sheet")).toBeInTheDocument();
  });

  it("an approver approves; the submitter can't", async () => {
    const pending = { ...ledger, status: "pending_approval" as const, can_edit: false, submitted_by: { id: 5, full_name: "Fatima Khan", role: "finance" as const } };
    const { post } = mockApi(makeUser("finance_approver"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/ledger": { ...pending, can_approve: true } },
      post: { "/post-sales/cases/4/ledger/approve": { ...pending, status: "approved" } } });
    renderApp("/post-sales/4");
    const panel = await openLedger();
    expect(panel).toHaveTextContent("Submitted by Fatima Khan");
    await userEvent.click(within(panel).getByRole("button", { name: "Approve ledger" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/ledger/approve", undefined));
    expect(await screen.findByText("Ledger approved")).toBeInTheDocument();
  });

  it("legal staff don't get the Ledger tab", async () => {
    mockApi(makeUser("legal"), { get: { "/post-sales/cases/4": kase } });
    renderApp("/post-sales/4");
    await screen.findByRole("tab", { name: "KYC" });
    expect(screen.queryByRole("tab", { name: "Ledger" })).not.toBeInTheDocument();
  });
});
