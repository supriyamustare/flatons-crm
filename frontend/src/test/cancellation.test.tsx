import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CaseDetail } from "../hooks/usePostSales";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const kase = { id: 4, case_code: "PSC-00004", status: "accepted", onboarding_status: "approved", customer: "Anita Desai", project: "Habitat", unit_no: "1114",
  booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-11-17", agreed_price: 3_225_000, owner: null, sales_exec: null, created_at: "2026-11-17T05:00:00Z",
  kyc_done: 4, kyc_total: 4, returned_reason: null, clarification_reason: null, accepted_at: "2026-11-17T05:00:00Z", handover: [], profile: null, co_applicants: [],
  requirements: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: false, history: [] } as unknown as CaseDetail;
const pos = { received: 322_500, received_own: 322_500, loan_disbursed: 0, unconfirmed_receipts: 0, outstanding_demands: 0, open_tickets: [] };
const reasons = { customer_request: "Customer request", loan_rejected: "Home loan rejected" };
const none = { cancellation: null, reasons, history: [], position: pos, can_request: true };
const live = (over: Record<string, unknown> = {}, can: Record<string, boolean> = {}) => ({ reasons, history: [], position: pos, can_request: false, cancellation: {
  id: 1, number: "CXL-00001", status: "settlement_proposed", initiated_by: "customer", reason_code: "loan_rejected", reason_label: "Home loan rejected", reason: "Loan rejected",
  request_date: "2026-11-20", effective_date: null, contract_clause: "Clause 12.2", supporting_document_ids: [], legal_review: { by_name: "Leela", at: "2026-11-20T06:00:00Z", note: "ok" },
  commercial_review: { by_name: "Meera", at: "2026-11-20T06:00:00Z", note: "ok" },
  settlement: { snapshot: pos, deductions: [{ label: "Forfeiture", amount: 32_250, basis: "Clause 12.2: 10% of amount paid" }], total_deductions: 32_250, refund: 290_250,
    balance_due_from_customer: 0, prepared_by: "Fatima", at: "2026-11-21T06:00:00Z", note: null },
  approvals: [], communication: null, refund_bank: null, refund_payment: null, release: null, end_reason: null, closed_at: null, can: { ...can }, ...over } });

describe("cancellation", () => {
  it("records a request with its reason and supporting documents", async () => {
    const { post } = mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/cancellation": none,
      "/post-sales/cases/4/documents": { documents: [{ id: 31, title: "Customer's cancellation email", doc_no: "DOC-00031" }] } },
      post: { "/post-sales/cases/4/cancellation": live({ status: "requested", settlement: null }) } });
    renderApp("/post-sales/4?tab=cancellation");
    const panel = await screen.findByRole("tabpanel", { name: "Cancellation" });
    expect(panel).toHaveTextContent("nothing is erased");
    await userEvent.click(within(panel).getByRole("button", { name: "Record a cancellation request" }));
    const d = await screen.findByRole("dialog", { name: "Cancellation request" });
    expect(within(d).getByRole("button", { name: "Record request" })).toBeDisabled();
    await userEvent.selectOptions(within(d).getByLabelText("Reason"), "loan_rejected");
    await userEvent.type(within(d).getByLabelText("Details"), "HDFC rejected the loan");
    await userEvent.click(within(d).getByLabelText(/Customer's cancellation email/));
    await userEvent.click(within(d).getByRole("button", { name: "Record request" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/cancellation", expect.objectContaining({ reason_code: "loan_rejected", supporting_document_ids: [31] })));
  });

  it("the settlement editor previews the refund and sends each deduction with its basis", async () => {
    const { put } = mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/cancellation": live({ status: "reviewed", settlement: null }, { settlement: true }),
      "/post-sales/cases/4/documents": { documents: [] } }, put: { "/post-sales/cases/4/cancellation/settlement": live() } });
    renderApp("/post-sales/4?tab=cancellation");
    await userEvent.click(await screen.findByRole("button", { name: "Calculate settlement" }));
    const d = await screen.findByRole("dialog", { name: "Settlement" });
    await userEvent.click(within(d).getByRole("button", { name: "Add deduction" }));
    await userEvent.type(within(d).getByLabelText("Deduction 1"), "Forfeiture");
    await userEvent.type(within(d).getByLabelText("Amount (₹)"), "32250");
    await userEvent.type(within(d).getByLabelText("Basis for deduction 1"), "Clause 12.2");
    expect(d).toHaveTextContent("Refund: ₹ 2,90,250");
    await userEvent.click(within(d).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/post-sales/cases/4/cancellation/settlement",
      { deductions: [{ label: "Forfeiture", amount: 32250, basis: "Clause 12.2" }], note: null }));
  });

  it("approval buttons follow the person; the letter is a draft until approved", async () => {
    mockApi(makeUser("finance_approver"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/cancellation": live({}, { approve_finance: true, reject: true }),
      "/post-sales/cases/4/documents": { documents: [] } } });
    renderApp("/post-sales/4?tab=cancellation");
    const set = await screen.findByRole("region", { name: "Settlement" });
    expect(within(set).getByRole("button", { name: "Approve (finance check)" })).toBeInTheDocument();
    expect(within(set).queryByRole("button", { name: "Approve (management)" })).not.toBeInTheDocument();
    expect(set).toHaveTextContent("Clause 12.2: 10% of amount paid");
  });

  it("the letter shows the settlement and is marked draft before approval", async () => {
    mockApi(makeUser("crm_manager"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/cancellation": live() } });
    renderApp("/cancellation-letter/4");
    const art = await screen.findByRole("article", { name: "Cancellation letter" });
    expect(within(art).getByLabelText("Draft")).toBeInTheDocument();
    expect(art).toHaveTextContent("Refund to you"); expect(art).toHaveTextContent("₹ 2,90,250"); expect(art).toHaveTextContent("under Clause 12.2");
  });
});
