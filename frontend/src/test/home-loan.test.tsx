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

async function openTab() {
  await userEvent.click(await screen.findByRole("tab", { name: "Loan" }));
  return screen.findByRole("tabpanel", { name: "Loan" });
}

describe("loan tab", () => {
  it("shows the workflow, warnings, bank requests and a delayed disbursement", async () => {
    mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/loan": base } });
    renderApp("/post-sales/4");
    const panel = await openTab();
    const prog = within(panel).getByRole("list", { name: "Loan progress" });
    expect(within(prog).getByText("Disbursement awaited").closest("li")).toHaveAttribute("aria-current", "step");
    expect(panel).toHaveTextContent("update the ledger's funding");
    const row = within(within(panel).getByRole("table", { name: "Disbursements" })).getByRole("row", { name: /DR-1/ });
    expect(row).toHaveTextContent("Delayed"); expect(row).toHaveTextContent("Bank's technical visit pending");
  });

  it("finance records funds received, creating the loan receipt", async () => {
    const { post } = mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/loan": base },
      post: { "/post-sales/cases/4/loan/disbursements/9/received": { ...base, disbursements: [{ ...base.disbursements[0], status: "received", state: "funds_received", delayed: false,
        actual_amount: 1_000_000, actual_date: "2026-11-19", utr: "HDFC-UTR-1", receipt_no: "RCT-00007", receipt_status: "recorded" }] } } });
    renderApp("/post-sales/4");
    const panel = await openTab();
    await userEvent.click(within(panel).getByRole("button", { name: "Funds received" }));
    const d = await screen.findByRole("dialog", { name: "Funds received from the bank" });
    expect(d).toHaveTextContent("counts, and is matched to stages, only once a finance approver confirms it");
    await userEvent.type(within(d).getByLabelText("UTR / reference"), "HDFC-UTR-1");
    await userEvent.click(within(d).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/loan/disbursements/9/received", expect.objectContaining({ actual_amount: 1_000_000, utr: "HDFC-UTR-1" })));
    expect(await within(panel).findByText(/RCT-00007/)).toBeInTheDocument();
  });

  it("post-sales staff can't record funds (that creates a receipt)", async () => {
    mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/loan": { ...base, can_record_funds: false } } });
    renderApp("/post-sales/4");
    const panel = await openTab();
    expect(within(panel).queryByRole("button", { name: "Funds received" })).not.toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Mark submitted" })).toBeInTheDocument();
  });

  it("adds a loan when there is none", async () => {
    const { post } = mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/loan": { ...base, loan: null, stages: [], disbursements: [], doc_requests: [], warnings: [] } },
      post: { "/post-sales/cases/4/loan": base } });
    renderApp("/post-sales/4");
    const panel = await openTab();
    const form = within(panel).getByRole("form", { name: "Loan details" });
    await userEvent.type(within(form).getByLabelText("Bank / lender"), "HDFC Bank");
    await userEvent.type(within(form).getByLabelText("Applied amount (₹)"), "26,00,000");
    await userEvent.click(within(form).getByRole("button", { name: "Add loan" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/loan", expect.objectContaining({ lender: "HDFC Bank", applied_amount: 2_600_000 })));
  });

  it("legal staff don't get the Loan tab", async () => {
    mockApi(makeUser("legal"), { get: { "/post-sales/cases/4": kase } });
    renderApp("/post-sales/4");
    await screen.findByRole("tab", { name: "KYC" });
    expect(screen.queryByRole("tab", { name: "Loan" })).not.toBeInTheDocument();
  });
});
