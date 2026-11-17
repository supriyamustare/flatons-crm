import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CaseDetail } from "../hooks/usePostSales";
import type { Receipt, Receipts } from "../hooks/useReceipts";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const kase = {
  id: 4, case_code: "PSC-00004", status: "accepted", onboarding_status: "documents_pending", customer: "Anita Desai", project: "Habitat", unit_no: "1114",
  booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-11-17", agreed_price: 3_225_000, owner: null, sales_exec: null, created_at: "2026-11-17T05:00:00Z",
  kyc_done: 0, kyc_total: 4, returned_reason: null, clarification_reason: null, accepted_at: "2026-11-17T05:00:00Z", handover: [], profile: null, co_applicants: [],
  requirements: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: false, history: [],
} as unknown as CaseDetail;
const booking: Receipt = {
  id: 1, receipt_no: "RCT-00001", amount: 322_500, received_on: "2026-11-17", mode: "neft", source: "own", payer_name: "Anita Desai", reference: "BKG-00009",
  bank_name: null, notes: null, from_booking: true, status: "recorded", matched: 322_500, unapplied: 0, matches: [{ stage_seq: 1, charge_head: null, amount: 322_500 }],
  recorded_by: { id: 5, full_name: "Fatima Test", role: "finance" }, recorded_at: "2026-11-17T06:00:00Z", confirmed_by: null, confirmed_at: null,
  void_reason: null, voided_at: null, can_match: false, can_confirm: true, can_bounce: false, can_reverse: false,
};
const data: Receipts = {
  ledger_exists: true, can_record: false, receipts: [booking],
  stages: [{ seq: 1, name: "Booking", due: "2026-11-17", total: 325_725, paid: 0, outstanding: 325_725, is_due: true },
    { seq: 2, name: "Registration", due: "Milestone: Registration", total: 325_725, paid: 0, outstanding: 325_725, is_due: false }],
  other_charges: [{ head: "stamp_duty", label: "Stamp duty", total: 225_800, paid: 0, outstanding: 225_800 }],
  balances: { received: 0, received_own: 0, loan_disbursed: 0, total_outstanding: 3_608_171, currently_demanded: 325_725, overdue: 0, own_contribution_required: 3_608_171,
    loan_not_disbursed: 0, under_dispute: 0, other_charges: 265_800, unapplied: 0, pending_confirmation: 322_500 },
};

async function openReceipts() {
  await userEvent.click(await screen.findByRole("tab", { name: "Receipts" }));
  return screen.findByRole("tabpanel", { name: "Receipts" });
}

describe("receipts tab", () => {
  it("finance records a receipt, matched oldest-first by default", async () => {
    const { post } = mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/receipts": { ...data, can_record: true, receipts: [{ ...booking, can_confirm: false }] } },
      post: { "/post-sales/cases/4/receipts": data } });
    renderApp("/post-sales/4");
    const panel = await openReceipts();
    expect(within(panel).getByText("Waiting for a finance approver")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Record receipt" }));
    const d = await screen.findByRole("dialog", { name: "Record receipt" });
    await userEvent.type(within(d).getByLabelText("Amount (₹)"), "3225");
    await userEvent.selectOptions(within(d).getByLabelText("Mode"), "upi");
    await userEvent.type(within(d).getByLabelText("UTR / transaction reference"), "upi-778");
    await userEvent.click(within(d).getByRole("button", { name: "Record receipt" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/receipts", expect.objectContaining({ amount: 3225, mode: "upi", reference: "upi-778", source: "own" })));
    expect((post.mock.calls[0][1] as Record<string, unknown>).matches).toBeUndefined();
    expect(await screen.findByText(/Receipt of ₹ 3,225 recorded/)).toBeInTheDocument();
  });

  it("cash of Rs 2 lakh or more is stopped before saving", async () => {
    mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/receipts": { ...data, can_record: true } } });
    renderApp("/post-sales/4");
    const panel = await openReceipts();
    await userEvent.click(within(panel).getByRole("button", { name: "Record receipt" }));
    const d = await screen.findByRole("dialog", { name: "Record receipt" });
    await userEvent.type(within(d).getByLabelText("Amount (₹)"), "250000");
    await userEvent.selectOptions(within(d).getByLabelText("Mode"), "cash");
    expect(within(d).getByRole("alert")).toHaveTextContent("section 269ST");
    expect(within(d).getByRole("button", { name: "Record receipt" })).toBeDisabled();
  });

  it("a finance approver confirms", async () => {
    const { post } = mockApi(makeUser("finance_approver"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/receipts": data },
      post: { "/post-sales/cases/4/receipts/1/confirm": { ...data, receipts: [{ ...booking, status: "confirmed", can_confirm: false }] } } });
    renderApp("/post-sales/4");
    const panel = await openReceipts();
    const row = within(panel).getByRole("row", { name: /RCT-00001/ });
    expect(row).toHaveTextContent("from the booking");
    await userEvent.click(within(row).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/receipts/1/confirm", undefined));
    expect(await screen.findByText("RCT-00001 confirmed")).toBeInTheDocument();
  });

  it("bounced receipts stay listed, struck through, with the reason", async () => {
    const bounced = { ...booking, id: 2, receipt_no: "RCT-00002", mode: "cheque" as const, reference: "000123", from_booking: false, status: "bounced" as const, void_reason: "Insufficient funds", can_confirm: false };
    mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/receipts": { ...data, receipts: [bounced, booking] } } });
    renderApp("/post-sales/4");
    const panel = await openReceipts();
    const row = within(panel).getByRole("row", { name: /RCT-00002/ });
    expect(row).toHaveTextContent("Bounced: Insufficient funds");
    expect(within(row).getByText("₹ 3,22,500")).toHaveClass("line-through");
    expect(within(row).getByLabelText("Not counted")).toHaveTextContent("—");
  });

  it("the statement of account lists the summary, stages and receipts", async () => {
    const ledger = { exists: true, status: "approved", version: 1, gst_pct: 1, loan_sanctioned: 0, lender: null, loan_reference: null, note: null, submitted_by: null,
      submitted_at: null, approved_by: null, approved_at: null, charges: [], schedule: [], problems: [], can_edit: false, can_approve: false, head_labels: {},
      totals: { agreement_value: 3_225_000, gst: 32_250, statutory: 255_800, other: 95_121, total_payable: 3_608_171, schedule_amount: 3_225_000, schedule_gst: 32_250 },
      balances: data.balances };
    mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/ledger": ledger, "/post-sales/cases/4/receipts": data } });
    renderApp("/statement/4");
    const st = await screen.findByRole("article", { name: "Statement of account" });
    expect(st).toHaveTextContent("Anita Desai");
    expect(st).toHaveTextContent("Total payable₹ 36,08,171");
    expect(st).toHaveTextContent("RCT-00001");
    expect(st).toHaveTextContent("Waiting for confirmation");
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });
});

describe("avoiding wrong entries", () => {
  it("the mode must be chosen, and a 'CASH' reference needs the Cash mode", async () => {
    mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/receipts": { ...data, can_record: true } } });
    renderApp("/post-sales/4");
    const panel = await openReceipts();
    await userEvent.click(within(panel).getByRole("button", { name: "Record receipt" }));
    const d = await screen.findByRole("dialog", { name: "Record receipt" });
    await userEvent.type(within(d).getByLabelText("Amount (₹)"), "250000");
    expect(within(d).getByLabelText("Mode")).toHaveValue("");
    expect(within(d).getByRole("button", { name: "Record receipt" })).toBeDisabled();
    await userEvent.selectOptions(within(d).getByLabelText("Mode"), "neft");
    await userEvent.type(within(d).getByLabelText("UTR / transaction reference"), "cash");
    expect(within(d).getByRole("alert")).toHaveTextContent("choose Cash as the mode");
    expect(within(d).getByRole("button", { name: "Record receipt" })).toBeDisabled();
  });

  it("approvers reject a receipt still waiting for confirmation; it shows as Rejected", async () => {
    const waiting = { ...booking, id: 4, receipt_no: "RCT-00004", from_booking: false, reference: "000123", can_reverse: true };
    const rejected = { ...waiting, status: "reversed" as const, void_reason: "Was a cheque, entered as NEFT", can_confirm: false, can_reverse: false };
    const { post } = mockApi(makeUser("finance_approver"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/receipts": { ...data, receipts: [waiting] } },
      post: { "/post-sales/cases/4/receipts/4/reverse": { ...data, receipts: [rejected] } } });
    renderApp("/post-sales/4");
    const panel = await openReceipts();
    await userEvent.click(within(within(panel).getByRole("row", { name: /RCT-00004/ })).getByRole("button", { name: "Reject" }));
    const d = await screen.findByRole("dialog", { name: "Reject RCT-00004" });
    await userEvent.type(within(d).getByLabelText("Reason"), "Was a cheque, entered as NEFT");
    await userEvent.click(within(d).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/receipts/4/reverse", { reason: "Was a cheque, entered as NEFT" }));
    expect(await within(panel).findByText("Rejected: Was a cheque, entered as NEFT")).toBeInTheDocument();
  });
});
