import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectAfterSales } from "../components/aftersales/ProjectAfterSales";
import type { CaseDetail } from "../hooks/usePostSales";
import { makeUser, mockApi } from "./mockApi";
import { renderApp, renderWithProviders } from "./render";

beforeEach(() => vi.restoreAllMocks());

const kase = { id: 4, case_code: "PSC-00004", status: "accepted", onboarding_status: "approved", customer: "Anita Desai", project: "Habitat", unit_no: "1114",
  booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-11-17", agreed_price: 3_225_000, owner: null, sales_exec: null, created_at: "2026-11-17T05:00:00Z",
  kyc_done: 4, kyc_total: 4, returned_reason: null, clarification_reason: null, accepted_at: "2026-11-17T05:00:00Z", handover: [], profile: null, co_applicants: [],
  requirements: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: false, history: [] } as unknown as CaseDetail;
const defect = (over: Record<string, unknown>) => ({ id: 2, number: "DEF-00002", project_id: 1, case_id: 4, customer: "Anita Desai", unit: "1114", status: "diagnosed",
  complaint_date: "2026-11-23", channel: "phone", category: "fittings", description: "Broken glass shelf", location: "Bathroom", item: null, warranty: null,
  warranty_start: null, warranty_end: null, in_warranty: null, owner: "Arjun", raised_by: "Pooja", steps: { diagnosis: { visited_on: "2026-11-23", text: "Impact damage" } },
  target_date: null, overdue: false, reopened_count: 0, closure_reason: null, closed_at: null, created_at: "2026-11-23T05:00:00Z", files: [], next: ["responsibility"], can_close: false, ...over });
const summary = (defects: unknown[]) => ({ project_id: 1, after_sales_since: "2026-11-23T06:00:00Z", possession_on: "2026-11-23", guidance: "Raise requests with the FM desk",
  maintenance_contacts: "FM desk 020-1234", can_raise: true, categories: [], owners: [],
  warranties: [{ id: 1, name: "Structural defects", category: "structural", provider: null, period_months: 60, starts_from: "possession", basis: "RERA s.14(3)", active: true,
    start: "2026-11-23", end: "2031-11-22", in_warranty: true }], defects });

describe("after-sales", () => {
  it("shows the transfer, warranty coverage with real dates, and the defect's next step", async () => {
    mockApi(makeUser("after_sales"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/after-sales": summary([defect({})]) } });
    renderApp("/post-sales/4?tab=aftersales");
    const panel = await screen.findByRole("tabpanel", { name: "After-sales" });
    expect(panel).toHaveTextContent("With the after-sales team since");
    expect(within(panel).getByRole("table", { name: "Warranty coverage" })).toHaveTextContent("2031-11-22");
    expect(within(panel).getByRole("table", { name: "Warranty coverage" })).toHaveTextContent("Covered");
    expect(within(panel).getByRole("button", { name: "Assign responsibility" })).toBeInTheDocument();
  });

  it("not covered asks for the reason and estimate", async () => {
    const { post } = mockApi(makeUser("after_sales"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/after-sales": summary([defect({})]) },
      post: { "/defects/2/step": defect({ status: "awaiting_customer_approval", next: [] }) } });
    renderApp("/post-sales/4?tab=aftersales");
    await userEvent.click(await screen.findByRole("button", { name: "Assign responsibility" }));
    const d = await screen.findByRole("dialog", { name: "DEF-00002: Assign responsibility" });
    await userEvent.selectOptions(within(d).getByLabelText("Responsible party"), "customer");
    await userEvent.selectOptions(within(d).getByLabelText("Covered by warranty?"), "no");
    expect(d).toHaveTextContent("can’t start until the customer approves the estimate");
    await userEvent.type(within(d).getByLabelText("Why it isn’t covered"), "Damage after possession");
    await userEvent.type(within(d).getByLabelText("Estimate for the work (₹)"), "1800");
    await userEvent.click(within(d).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/defects/2/step", { step: "responsibility", data: expect.objectContaining({ party: "customer", covered: false, estimate: 1800, reason: "Damage after possession" }) }));
  });

  it("warranty terms are read-only for non-editors and saved by editors", async () => {
    const proj = (can_edit: boolean) => ({ warranties: [{ id: 1, name: "Structural defects", category: "structural", provider: null, period_months: 60, starts_from: "possession", basis: "RERA", active: true }],
      facility: {}, can_edit, pending_common_area_defects: [] });
    mockApi(makeUser("after_sales"), { get: { "/projects/1/after-sales": proj(false), "/defects": [] } });
    const { unmount } = renderWithProviders(<ProjectAfterSales projectId={1} />);
    expect(await screen.findByLabelText("Term 1")).toBeDisabled();
    unmount(); vi.restoreAllMocks();
    const { put } = mockApi(makeUser("legal"), { get: { "/projects/1/after-sales": proj(true), "/defects": [] }, put: { "/projects/1/warranties": proj(true) } });
    renderWithProviders(<ProjectAfterSales projectId={1} />);
    await userEvent.click(await screen.findByRole("button", { name: "Add term" }));
    await userEvent.type(screen.getByLabelText("Term 2"), "Waterproofing");
    const months = screen.getAllByLabelText("Months")[1]; await userEvent.clear(months); await userEvent.type(months, "24");
    await userEvent.click(screen.getByRole("button", { name: "Save terms" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/projects/1/warranties", [expect.objectContaining({ id: 1, period_months: 60 }), expect.objectContaining({ name: "Waterproofing", period_months: 24 })]));
  });
});
