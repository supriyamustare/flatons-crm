import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LoanRow, LoanState } from "../hooks/useLoan";
import type { CaseDetail } from "../hooks/usePostSales";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());
const kase = {
  id: 4, case_code: "PSC-00004", status: "accepted", onboarding_status: "approved", customer: "Anita Desai", project: "Habitat", unit_no: "1114",
  booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-11-17", agreed_price: 3_225_000, owner: null, sales_exec: null, created_at: "2026-11-17T05:00:00Z",
  kyc_done: 4, kyc_total: 4, returned_reason: null, clarification_reason: null, accepted_at: "2026-11-17T05:00:00Z", handover: [], profile: null, co_applicants: [],
  requirements: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: false, history: [],
} as unknown as CaseDetail;
const labels = ["Loan details captured", "Documents requested", "Documents submitted", "Bank review", "Disbursement requested", "Disbursement awaited", "Funds received", "Reconciled"];
const stages = (cur: number) => labels.map((label, i) => ({ key: String(i), label, done: i < cur, current: i === cur }));
const loan: LoanRow = { id: 1, lender: "HDFC Bank", application_no: "HL-001", consent_on: "2026-11-18", applied_amount: 2_600_000, sanctioned_amount: 2_500_000,
  sanction_date: "2026-11-18", sanction_valid_until: "2026-12-01", rm_name: "Suresh Iyer", rm_phone: "9822011111", rm_email: null, technical_status: "cleared", legal_status: "in_progress",
  pending_conditions: null, owner_id: null, next_follow_up_on: null, close_reason: null, received_total: 0, remaining: 2_500_000 };
const base: LoanState = { loan, history: [], stage: "disbursement_awaited", stages: stages(5), doc_requests: [{ id: 3, name: "Allotment letter", requested_on: "2026-11-18", note: null, submitted_on: null }],
  disbursements: [{ id: 9, request_no: "DR-1", request_date: "2026-11-10", for_stage: "Plinth", expected_amount: 1_000_000, expected_date: "2026-11-15", status: "awaited",
    delay_reason: "Bank's technical visit pending", actual_date: null, actual_amount: null, utr: null, state: "disbursement_awaited", delayed: true, receipt_no: null, receipt_status: null }],
  ledger_loan: 0, warnings: ["The ledger's loan is Rs 0 but Rs 2,500,000 is sanctioned; update the ledger's funding"], owners: [], can_edit: true, can_record_funds: true };
const ocr = (over: Record<string, unknown> = {}) => ({ plan: { own_amount: 400_000, note: "10% own", status: "draft", entered_by: "Pooja", approved_by: null, approved_at: null, history: [] },
  total_payable: 3_523_050, charges_own: 265_800, loan_needed: 2_857_250, sanctioned: 2_500_000, lender: "HDFC Bank", shortfall: 357_250, own_required: 757_250,
  received_own: 322_500, pending_own: 0, remaining_own: 434_750, own_due_now: 3_225, own_overdue: 0,
  stages: [{ stage: "Booking", amount: 325_725, own_part: 325_725, loan_part: 0, due_date: "2026-11-26", demanded: true, own_outstanding: 3_225, overdue: false },
    { stage: "Plinth", amount: 325_725, own_part: 74_275, loan_part: 251_450, due_date: null, demanded: false, own_outstanding: 0, overdue: false }],
  receipts: [{ receipt_no: "RCT-00001", date: "2026-11-26", amount: 322_500, mode: "neft", status: "confirmed" }],
  warnings: ["The bank approved Rs 2,500,000 but the loan needed is Rs 2,857,250: the customer must pay the Rs 357,250 difference from own funds."], can_edit: true, can_approve: true, ...over });

describe("OCR and the sanction letter", () => {
  it("shows the own contribution, the loan and the bank shortfall", async () => {
    const { post } = mockApi(makeUser("finance_approver"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/ocr": ocr() }, post: { "/post-sales/cases/4/ocr/approve": ocr({ can_approve: false }) } });
    renderApp("/post-sales/4?tab=ocr");
    const panel = await screen.findByRole("tabpanel", { name: "OCR" });
    expect(panel).toHaveTextContent("must pay the Rs 357,250 difference");
    const funding = within(panel).getByText("Loan needed").closest("dl")!;
    expect(funding).toHaveTextContent("Loan needed₹ 28,57,250"); expect(funding).toHaveTextContent("Shortfall to pay from own funds₹ 3,57,250");
    expect(within(panel).getByRole("table", { name: "Own share and loan share by stage" })).toHaveTextContent("Plinth");
    await userEvent.click(within(panel).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/ocr/approve"));
  });

  it("sets a fixed own contribution", async () => {
    const { put } = mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/ocr": ocr({ plan: null, can_approve: false, stages: [], warnings: [] }) },
      put: { "/post-sales/cases/4/ocr": ocr() } });
    renderApp("/post-sales/4?tab=ocr");
    await userEvent.click(await screen.findByRole("button", { name: "Set own contribution" }));
    await userEvent.type(screen.getByLabelText("Own contribution (₹, fixed amount)"), "400000");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/post-sales/cases/4/ocr", { own_amount: 400000, note: null, reason: null }));
  });

  it("the Loan tab shows the approved amount with the sanction letter", async () => {
    const withLetter = { ...base, sanction_letter: { id: 21, doc_no: "DOC-00021", title: "Loan sanction letter: HDFC Bank", approval: "under_approval", visibility: "internal",
      url: "/api/post-sales/documents/21/file", sanctioned_amount: 2_500_000, sanction_date: "2026-11-18", valid_until: "2027-05-17" } };
    mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/loan": withLetter } });
    renderApp("/post-sales/4?tab=loan");
    const sec = await screen.findByRole("region", { name: "Sanction letter" });
    expect(sec).toHaveTextContent("Loan approved: ₹ 25,00,000 on 2026-11-18");
    expect(within(sec).getByRole("link", { name: /Loan sanction letter: HDFC Bank/ })).toHaveAttribute("href", "/api/post-sales/documents/21/file");
  });
});
