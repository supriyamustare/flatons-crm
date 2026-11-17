import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectMilestones } from "../components/inventory/Milestones";
import type { Demand, Demands, Milestone } from "../hooks/useDemands";
import type { CaseDetail } from "../hooks/usePostSales";
import { makeUser, mockApi } from "./mockApi";
import { renderApp, renderWithProviders } from "./render";

beforeEach(() => vi.restoreAllMocks());

const kase = {
  id: 4, case_code: "PSC-00004", status: "accepted", onboarding_status: "documents_pending", customer: "Anita Desai", project: "Habitat", unit_no: "1114",
  booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-11-17", agreed_price: 3_225_000, owner: null, sales_exec: null, created_at: "2026-11-17T05:00:00Z",
  kyc_done: 0, kyc_total: 4, returned_reason: null, clarification_reason: null, accepted_at: "2026-11-17T05:00:00Z", handover: [], profile: null, co_applicants: [],
  requirements: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: false, history: [],
} as unknown as CaseDetail;
const draft: Demand = {
  id: 7, demand_no: "DMD-00007", version: 1, stage_seq: 3, stage_name: "Plinth", stage_amount: 325_725, previous_dues: 3_225, total_due: 328_950,
  demanded_on: "2026-11-17", due_date: "2026-12-02", status: "draft", payment: "—", outstanding_now: 325_725, note: null, cancel_reason: null, issue_method: null,
  prepared_by: null, submitted_by: null, approved_by: null, issued_by: null, issued_at: null, supersedes: null,
  can_submit: true, can_approve: false, can_issue: false, can_cancel: false,
};
const ready: Demands = { demands: [draft], can_create: [], ledger_approved: true, readiness: { ready: true, missing: [] } };

async function openDemands() {
  await userEvent.click(await screen.findByRole("tab", { name: "Demands" }));
  return screen.findByRole("tabpanel", { name: "Demands" });
}

describe("milestones", () => {
  const plinth: Milestone = { id: null, name: "Plinth", status: "planned", completed_on: null, note: null, returned_reason: null, reported_by: null, reported_at: null,
    verified_by: null, verified_at: null, evidence: [], can_report: true, can_verify: false };
  it("site staff report a milestone with evidence", async () => {
    const { post } = mockApi(makeUser("site"), { get: { "/projects/1/milestones": [plinth] }, post: { "/projects/1/milestones/report": { ...plinth, status: "reported" } } });
    renderWithProviders(<ProjectMilestones projectId={1} />);
    await userEvent.click(await screen.findByRole("button", { name: "Report complete" }));
    const d = await screen.findByRole("dialog", { name: "Report complete: Plinth" });
    expect(within(d).getByRole("button", { name: "Report complete" })).toBeDisabled();  // evidence needed
    await userEvent.upload(within(d).getByLabelText("Evidence (photos or certificates)"), new File([new Uint8Array([0x89, 0x50])], "slab.png", { type: "image/png" }));
    await userEvent.click(within(d).getByRole("button", { name: "Report complete" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, form] = post.mock.calls[0] as [string, FormData];
    expect(url).toBe("/projects/1/milestones/report");
    expect([form.get("name"), (form.get("files") as File).name]).toEqual(["Plinth", "slab.png"]);
  });

  it("a CRM manager verifies and sees what it did", async () => {
    const reported = { ...plinth, id: 3, status: "reported" as const, completed_on: "2026-11-16", can_report: false, can_verify: true };
    mockApi(makeUser("crm_manager"), { get: { "/projects/1/milestones": [reported] },
      post: { "/projects/1/milestones/3/verify": { cases: 3, demands: 2, ledgers_not_approved: 1, due_date: "2026-12-02" } } });
    renderWithProviders(<ProjectMilestones projectId={1} />);
    await userEvent.click(await screen.findByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Plinth verified: 3 bookings demanded (due 2026-12-02), 2 draft demands; 1 ledgers not yet approved")).toBeInTheDocument();
  });
});

describe("demands tab", () => {
  it("submitting is blocked until the project's details are complete", async () => {
    mockApi(makeUser("finance"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/demands": { ...ready, readiness: { ready: false, missing: ["GSTIN", "Account number"] } } } });
    renderApp("/post-sales/4");
    const panel = await openDemands();
    expect(panel).toHaveTextContent("Demand letters need the project’s details first: GSTIN, Account number");
    expect(within(panel).getByRole("button", { name: "Submit for approval" })).toBeDisabled();
    expect(within(panel).getByRole("link", { name: "Letter" })).toHaveAttribute("href", "/demand-letter/4/7");
  });

  it("approve, then issue with how it was sent", async () => {
    const pending = { ...draft, status: "pending_approval" as const, can_submit: false, can_approve: true, can_cancel: true };
    const approved = { ...pending, status: "approved" as const, can_approve: false, can_issue: true };
    const { post } = mockApi(makeUser("finance_approver"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/demands": { ...ready, demands: [pending] } },
      post: { "/post-sales/cases/4/demands/7/approve": { ...ready, demands: [approved] }, "/post-sales/cases/4/demands/7/issue": { ...ready, demands: [{ ...approved, status: "issued", can_issue: false, payment: "unpaid", issue_method: "courier" }] } } });
    renderApp("/post-sales/4");
    const panel = await openDemands();
    await userEvent.click(within(panel).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("DMD-00007 approved")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Mark issued" }));
    const d = await screen.findByRole("dialog", { name: "Issue DMD-00007" });
    await userEvent.selectOptions(within(d).getByLabelText("Sent by"), "courier");
    await userEvent.click(within(d).getByRole("button", { name: "Mark issued" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/demands/7/issue", { method: "courier" }));
    expect(await within(panel).findByText("Unpaid")).toBeInTheDocument();
  });

  it("cancel needs a reason and drafts a new version by default", async () => {
    const issued = { ...draft, status: "issued" as const, can_submit: false, can_cancel: true, payment: "unpaid" };
    const { post } = mockApi(makeUser("finance_approver"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/demands": { ...ready, demands: [issued] } },
      post: { "/post-sales/cases/4/demands/7/cancel": ready } });
    renderApp("/post-sales/4");
    const panel = await openDemands();
    await userEvent.click(within(panel).getByRole("button", { name: "Cancel…" }));
    const d = await screen.findByRole("dialog", { name: "Cancel DMD-00007" });
    expect(within(d).getByRole("button", { name: "Cancel demand" })).toBeDisabled();
    await userEvent.type(within(d).getByLabelText("Reason"), "Wrong address");
    await userEvent.click(within(d).getByRole("button", { name: "Cancel demand" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/demands/7/cancel", { reason: "Wrong address", reissue: true }));
  });

  it("the letter is marked DRAFT before approval", async () => {
    const letter = { demand_no: "DMD-00007", case_code: "PSC-00004", booking_code: "BKG-00009", customer: "Anita Desai", co_applicants: null, address: "Baner, Pune",
      project: "Habitat", unit_no: "1114", agreed_price: 3_225_000, stage: "Plinth", stage_base: 322_500, stage_gst: 3_225, stage_amount: 325_725, previous_dues: 3_225,
      total_due: 328_950, demanded_on: "2026-11-17", due_date: "2026-12-02", notes: [], status: "draft", draft: true, cancelled: false, cancel_reason: null, version: 1,
      developer: { name: "Avnee Estates LLP", rera: "P52100099999", address: "Kharadi", gstin: "27ABCFA1234K1ZP", signatory: "Rahul Test", designation: "Partner" },
      bank: { name: "HDFC Bank", holder: "Avnee Estates LLP", account: "50200012345678", ifsc: "HDFC0001234", branch: "Kharadi" } };
    mockApi(makeUser("finance"), { get: { "/post-sales/cases/4/demands/7/letter": letter } });
    renderApp("/demand-letter/4/7");
    const art = await screen.findByRole("article", { name: "Demand letter" });
    expect(art).toHaveTextContent("DRAFT · NOT FOR ISSUE");
    expect(art).toHaveTextContent("Total payable by 2 December 2026₹ 3,28,950");
    expect(art).toHaveTextContent("50200012345678");
  });
});
