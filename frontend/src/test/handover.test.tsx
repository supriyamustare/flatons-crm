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
const snag = (over: Record<string, unknown>) => ({ id: 3, description: "Exposed wiring", location: "Kitchen", owner: "Sam Site", due_on: "2026-11-25", status: "open", note: null,
  category: "electrical", severity: "major", source: "internal", inspection_id: 1, rectification: null, fixed_at: null, verified_at: null, customer_response: null, customer_note: null,
  reopen_reason: null, reopened_count: 0, closed_at: null, reported_on: "2026-11-23T05:00:00Z", evidence: [], overdue: false, ...over });
const file = (over: Record<string, unknown> = {}) => ({
  started_at: "2026-11-20T05:00:00Z", start_reason: null, financial: { has_ledger: false }, finance: {}, clearance: { requested_at: null, cleared_at: null, snapshot: null },
  documents: [], readiness: [], meters: {}, snags: [], evidence_count: 1, readiness_approved_by: "Raj Test", readiness_approved_at: "2026-11-22T05:00:00Z", readiness_blockers: [],
  internal_approved_by: null, internal_approved_at: null, exception: null, owners: [{ id: 7, full_name: "Sam Site", role: "site" }],
  gate: { conditions: [{ key: "inspection", label: "Customer inspection done; no open major or critical snags", met: false, excepted: false }], open: false, detail: {} },
  can: { documents: true, inspect: true, approve_readiness: false, internal: false, exception: false, finance: false },
  inspections: [{ id: 1, conducted_on: "2026-11-23", attendees: "Anita, Pooja", notes: null, report_shared_on: null, report_shared_via: null, appointment_id: null }],
  handover: {}, handover_completed_at: null, actual_possession_on: null, possession_documents: [{ id: 21, title: "Signed handover checklist" }],
  possession_status: { status: "readiness_in_progress", label: "Readiness in progress", pending: [{ key: "snag_rectification", label: "Snag rectification" }, { key: "financial_clearance_pending", label: "Financial clearance pending" }] },
  dates: { construction_completed: "2026-11-15", possession_offered: null, legally_eligible: null, actual_possession: null }, ...over });
const st = (f: unknown) => ({ trigger: "OC", trigger_reached: true, can_start: false, file: f });

describe("inspection, snags and handover", () => {
  it("shows the status with parallel pending items and the four dates", async () => {
    mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/possession": st(file()) } });
    renderApp("/post-sales/4?tab=possession");
    const p = await screen.findByRole("region", { name: "Possession status" });
    expect(p).toHaveTextContent("Readiness in progress"); expect(p).toHaveTextContent("Snag rectification"); expect(p).toHaveTextContent("Financial clearance pending");
    expect(p).toHaveTextContent("Construction completed2026-11-15"); expect(p).toHaveTextContent("Actual possession—");
  });

  it("a major snag needs a completion photo before 'fixed'; customers accept repairs", async () => {
    const { post } = mockApi(makeUser("site"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/possession": st(file({ snags: [snag({}), snag({ id: 4, description: "Door latch", severity: "minor", source: "customer", status: "verified" })] })) },
      post: { "/post-sales/cases/4/possession/snags/4/customer": st(file()) } });
    renderApp("/post-sales/4?tab=possession");
    const reg = await screen.findByRole("region", { name: "Snag register" });
    expect(reg).toHaveTextContent("SNG-00003 · Exposed wiring");
    await userEvent.click(within(reg).getByRole("button", { name: "Fixed…" }));
    const d = await screen.findByRole("dialog", { name: "Mark fixed" });
    await userEvent.type(within(d).getByLabelText("Rectification details"), "Wiring enclosed in conduit");
    expect(within(d).getByRole("button", { name: "Save" })).toBeDisabled();
    expect(d).toHaveTextContent("Completion photo (required)");
    await userEvent.click(within(d).getByRole("button", { name: "Cancel" }));
    await userEvent.click(within(reg).getByRole("button", { name: "Customer accepted" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/possession/snags/4/customer", { response: "accepted" }));
  });

  it("the handover completes only once the required items are saved and the gate is open", async () => {
    const { post } = mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/possession": st(file({ gate: { conditions: [], open: true, detail: {} },
      handover: { identity_verified: true, keys_count: 3, customer_acknowledged: true, signed_checklist_document_id: 21 } })) },
      post: { "/post-sales/cases/4/possession/handover/complete": st(file({ handover_completed_at: "2026-11-23T08:00:00Z", actual_possession_on: "2026-11-23" })) } });
    renderApp("/post-sales/4?tab=possession");
    const h = await screen.findByRole("region", { name: "Possession handover" });
    expect(within(h).getByLabelText("Keys handed over (number)")).toHaveValue(3);
    await userEvent.click(within(h).getByRole("button", { name: "Complete handover" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/possession/handover/complete", expect.objectContaining({ actual_possession_on: expect.any(String) })));
  });

  it("without the required items, Complete stays disabled", async () => {
    mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/possession": st(file({ gate: { conditions: [], open: true, detail: {} } })) } });
    renderApp("/post-sales/4?tab=possession");
    const h = await screen.findByRole("region", { name: "Possession handover" });
    expect(within(h).getByRole("button", { name: "Complete handover" })).toBeDisabled();
  });

  it("the inspection report lists that inspection's snags", async () => {
    mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/possession": st(file({ snags: [snag({}), snag({ id: 5, description: "Other", inspection_id: 2 })] })) } });
    renderApp("/inspection-report/4/1");
    const art = await screen.findByRole("article", { name: "Inspection report" });
    expect(art).toHaveTextContent("Exposed wiring"); expect(art).not.toHaveTextContent("Other"); expect(art).toHaveTextContent("Items to be rectified (1)");
  });
});
