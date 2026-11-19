import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Agreement } from "../hooks/useAgreement";
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
const none = { agreement: null, history: [], checks: [], can: { initiate: false } };
const draft = { agreement_no: "AGR-00001", version: 1, date: "2026-11-18", agreement_value: 3_225_000, gst: 32_250, gst_pct: 1, placeholder_clauses: true,
  clauses: ["[PLACEHOLDER: replace] Unit 1114 in Habitat for Rs 32,25,000"], developer: { name: "Avnee Estates LLP", address: "Kharadi", gstin: "27ABCFA1234K1ZP", cin: null,
  signatory: "Rahul Test", designation: "Partner", rera: "P52100099999" }, purchasers: [{ name: "Anita Desai", pan: "ABCPD1234E", share: null }],
  unit: { project: "Habitat", location: "Kharadi", building: "Habitat", floor: 11, unit_no: "1114", type: "studio", carpet_sqft: 141.87, saleable_sqft: 205.71 },
  consideration: [{ label: "Base price (agreed)", amount: 3_225_000 }], schedule: [{ name: "Booking", amount: 322_500, gst: 3_225, due: "On booking" }] };
const ag = (over: Partial<Agreement>): Agreement => ({ id: 1, agreement_no: "AGR-00001", status: "internal_review", version: 1, draft, legal_approved_by: null, legal_approved_at: null,
  finance_approved_by: null, finance_approved_at: null, changes_note: null, shared_on: null, share_method: null, customer_accepted_on: null, stamp_duty_amount: null,
  stamp_duty_paid_on: null, stamp_duty_ref: null, registration_fee_amount: null, registration_fee_paid_on: null, registration_fee_ref: null, appointment_at: null,
  sro_office: null, id_docs_ready: false, signing_note: null, executed_on: null, registration_no: null, registered_on: null, final_document: null, cancel_reason: null,
  drafted_by_id: 7, ...over });

async function openTab() {
  await userEvent.click(await screen.findByRole("tab", { name: "Agreement" }));
  return screen.findByRole("tabpanel", { name: "Agreement" });
}

describe("agreement tab", () => {
  it("shows what's missing before it can start", async () => {
    mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/agreement": { ...none,
      conditions: [{ item: "KYC approved", ok: true }, { item: "At least 10% of the agreement value received (Rs 322,500)", ok: false, detail: "Received Rs 0" }] } } });
    renderApp("/post-sales/4");
    const panel = await openTab();
    const list = within(panel).getByRole("region", { name: "Ready to start the agreement?" });
    expect(list).toHaveTextContent("KYC approved: done"); expect(list).toHaveTextContent("Received Rs 0");
    expect(within(panel).queryByRole("button", { name: "Start agreement" })).not.toBeInTheDocument();
  });

  it("starts when ready", async () => {
    const { post } = mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/agreement": { ...none, conditions: [{ item: "KYC approved", ok: true }], can: { initiate: true } } },
      post: { "/post-sales/cases/4/agreement/initiate": { ...none, conditions: [], agreement: ag({ status: "initiated", version: 0, draft: null }), can: {} } } });
    renderApp("/post-sales/4");
    const panel = await openTab();
    await userEvent.click(within(panel).getByRole("button", { name: "Start agreement" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/agreement/initiate", undefined));
    expect(await within(panel).findByRole("list", { name: "Agreement progress" })).toHaveTextContent("Initiated");
  });

  it("internal review shows both approvals and warns about placeholder clauses", async () => {
    const legal = { id: 8, full_name: "Leela Test", role: "legal" as const };
    mockApi(makeUser("finance_approver"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/agreement": { ...none, conditions: [],
      agreement: ag({ legal_approved_by: legal, legal_approved_at: "2026-11-18T06:00:00Z" }), can: { approve_finance: true, request_changes: true } } } });
    renderApp("/post-sales/4");
    const panel = await openTab();
    expect(panel).toHaveTextContent("Legal: approved by Leela Test"); expect(panel).toHaveTextContent("Finance: waiting");
    expect(within(panel).getByRole("button", { name: "Approve (finance)" })).toBeInTheDocument();
    expect(panel).toHaveTextContent("clauses are still placeholders");
    expect(within(panel).getByRole("link", { name: "View draft" })).toHaveAttribute("href", "/agreement-draft/4");
  });

  it("records the registration", async () => {
    const { post } = mockApi(makeUser("legal"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/agreement": { ...none, conditions: [],
      agreement: ag({ status: "execution_prep", stamp_duty_amount: 225_800 }), can: { prepare: true, register: true } } },
      post: { "/post-sales/cases/4/agreement/register": { ...none, conditions: [], agreement: ag({ status: "registered", registration_no: "HVL-1-777-2026", executed_on: "2026-11-18", registered_on: "2026-11-18" }), can: { upload_final: true } } } });
    renderApp("/post-sales/4");
    const panel = await openTab();
    expect(within(panel).getByLabelText("Stamp duty (₹)")).toHaveValue("225800");
    await userEvent.click(within(panel).getByRole("button", { name: "Record signing and registration" }));
    const d = await screen.findByRole("dialog", { name: "Signing and registration" });
    await userEvent.type(within(d).getByLabelText("Registration number"), "HVL-1-777-2026");
    await userEvent.click(within(d).getByRole("button", { name: "Record registration" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/agreement/register", expect.objectContaining({ registration_no: "HVL-1-777-2026" })));
    expect(await within(panel).findByRole("button", { name: "Upload signed agreement" })).toBeInTheDocument();
  });

  it("the draft page is marked DRAFT and highlights placeholder clauses", async () => {
    mockApi(makeUser("legal"), { get: { "/post-sales/cases/4/agreement": { ...none, conditions: [], agreement: ag({}), can: {} } } });
    renderApp("/agreement-draft/4");
    const art = await screen.findByRole("article", { name: "Agreement draft" });
    expect(art).toHaveTextContent("Draft version 1"); expect(art).toHaveTextContent("AGREEMENT FOR SALE");
    expect(art).toHaveTextContent("Agreement value₹ 32,25,000"); expect(art).toHaveTextContent("PAN ABCPD1234E");
    expect(screen.getByText(/Contains placeholder clauses/)).toBeInTheDocument();
  });
});
