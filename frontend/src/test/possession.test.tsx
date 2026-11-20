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
const conds = (met: Record<string, boolean>, exc: string[] = []) => ["legal", "documents", "finance", "readiness", "internal", "communication"].map((k) => ({ key: k,
  label: { legal: "Legal and statutory readiness", documents: "Possession documents", finance: "Finance clearance", readiness: "Unit readiness approved",
    internal: "Internal approval (CRM manager)", communication: "Customer informed (possession letter released)" }[k], met: !!met[k], excepted: !met[k] && exc.includes(k) }));
const file = (over: Record<string, unknown> = {}) => ({
  started_at: "2026-11-20T05:00:00Z", start_reason: null,
  financial: { has_ledger: true, ledger_approved: true, total_payable: 3_608_171, received: 3_000_000, outstanding: 608_171, overdue: 0, demanded_not_yet_due: 162_856,
    not_yet_demanded: [], other_charges_outstanding: 350_921, unallocated: 0, unconfirmed_receipts: 0, pending_amount: 0, loan_not_disbursed: 0, open_disputes: [], final_demand_raised: true },
  finance: { taxes_confirmed: true, payment_confirmed: true }, clearance: { requested_by: null, requested_at: null, snapshot: null, cleared_by: null, cleared_at: null, note: null, returned_reason: null },
  documents: [{ item: "Executed agreement", status: "available" }, { item: "Occupancy or completion certificate", status: "pending" }],
  readiness: [{ item: "Doors, windows and hardware checked", status: "pending" }], meters: {}, snags: [], evidence_count: 0,
  readiness_approved_by: null, readiness_approved_at: null, readiness_blockers: ["Items not OK: Doors, windows and hardware checked", "No inspection evidence in 09 Possession & Handover"],
  internal_approved_by: null, internal_approved_at: null, exception: null,
  gate: { conditions: conds({ legal: true }), open: false, detail: { legal: null } },
  can: { finance: false, request_clearance: false, clear: false, documents: true, inspect: true, approve_readiness: true, internal: false, exception: false },
  owners: [{ id: 7, full_name: "Sam Site", role: "site" }], ...over });

async function openTab() {
  return screen.findByRole("tabpanel", { name: "Possession" });
}

describe("possession", () => {
  it("before the file: the trigger, and an early start needs a reason", async () => {
    const { post } = mockApi(makeUser("admin"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/possession": { trigger: "OC", trigger_reached: false, file: null, can_start: true } },
      post: { "/post-sales/cases/4/possession/start": { trigger: "OC", trigger_reached: false, file: file({ start_reason: "Customer relocating early" }), can_start: false } } });
    renderApp("/post-sales/4?tab=possession");
    const panel = await openTab();
    expect(panel).toHaveTextContent("OC milestone is verified: Not yet");
    await userEvent.click(within(panel).getByRole("button", { name: "Start pre-possession" }));
    const d = await screen.findByRole("dialog", { name: "Start before the milestone" });
    expect(within(d).getByRole("button", { name: "Start" })).toBeDisabled();
    await userEvent.type(within(d).getByLabelText("Reason"), "Customer relocating early");
    await userEvent.click(within(d).getByRole("button", { name: "Start" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/possession/start", { reason: "Customer relocating early" }));
  });

  it("shows the gate (met, missing, exception) and the finance figures", async () => {
    const ex = { by_name: "Meera Test", at: "2026-11-20T06:00:00Z", reason: "MD approved early possession", scope: ["finance"] };
    mockApi(makeUser("crm_manager"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/possession": { trigger: "OC", trigger_reached: true, can_start: false,
      file: file({ exception: ex, gate: { conditions: conds({ legal: true }, ["finance"]), open: false, detail: { legal: null } } }) } } });
    renderApp("/post-sales/4?tab=possession");
    const gate = within(await openTab()).getByRole("region", { name: "Possession gate" });
    expect(gate).toHaveTextContent("not yet");
    const financeItem = within(gate).getAllByRole("listitem").find((li) => li.textContent?.startsWith("Finance clearance"));
    expect(financeItem).toHaveTextContent("(exception)");
    expect(gate).toHaveTextContent("Exception by Meera Test");
    expect(screen.getByRole("region", { name: "Financial checklist" })).toHaveTextContent("Outstanding₹ 6,08,171");
  });

  it("'Not applicable' asks why", async () => {
    const { put } = mockApi(makeUser("legal"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/possession": { trigger: "OC", trigger_reached: true, file: file(), can_start: false } },
      put: { "/post-sales/cases/4/possession/documents": { trigger: "OC", trigger_reached: true, file: file(), can_start: false } } });
    renderApp("/post-sales/4?tab=possession");
    const docs = within(await openTab()).getByRole("region", { name: "Document checklist" });
    const row = within(docs).getByText("Occupancy or completion certificate").closest("li")!;
    await userEvent.click(within(row).getByRole("button", { name: "Not applicable" }));
    const d = await screen.findByRole("dialog", { name: "Not applicable: Occupancy or completion certificate" });
    await userEvent.type(within(d).getByLabelText("Why doesn’t it apply?"), "Not required for this commercial unit");
    await userEvent.click(within(d).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/post-sales/cases/4/possession/documents",
      { items: [{ item: "Occupancy or completion certificate", status: "not_applicable", note: "Not required for this commercial unit" }] }));
  });

  it("readiness approval waits for its blockers; snags take an owner and a date", async () => {
    const { post } = mockApi(makeUser("project_manager"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/possession": { trigger: "OC", trigger_reached: true, file: file(), can_start: false } },
      post: { "/post-sales/cases/4/possession/snags": { trigger: "OC", trigger_reached: true, file: file(), can_start: false } } });
    renderApp("/post-sales/4?tab=possession");
    const ready = within(await openTab()).getByRole("region", { name: "Unit readiness" });
    expect(within(ready).getByRole("button", { name: "Approve readiness" })).toBeDisabled();
    expect(ready).toHaveTextContent("No inspection evidence");
    await userEvent.click(within(ready).getByRole("button", { name: "Add snag" }));
    const d = await screen.findByRole("dialog", { name: "Add a snag" });
    await userEvent.type(within(d).getByLabelText("What needs fixing"), "Hairline crack near window");
    await userEvent.selectOptions(within(d).getByLabelText("Rectification owner"), "7");
    const due = new Date(Date.now() + 5 * 864e5).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
    await userEvent.type(within(d).getByLabelText("Fix by"), due);
    await userEvent.click(within(d).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/possession/snags", expect.objectContaining({ owner_id: 7, due_on: due })));
  });
});
