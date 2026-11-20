import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const settings = (can_edit: boolean) => ({
  response_hours: { urgent: 2, high: 4, normal: 24, low: 48 }, resolution_hours: { urgent: 24, high: 72, normal: 168, low: 360 }, at_risk_pct: 25, reopen_days: 14,
  categories: { defect: { team: "after_sales", needs_confirmation: true }, document: { team: "crm", needs_confirmation: false } },
  escalation: { level2_roles: ["crm_manager"], level3_roles: ["admin", "management"], level3_after_hours: 24 },
  labels: { defect: "Defect or warranty complaint", document: "Document download request" }, teams: { crm: "CRM", after_sales: "After-sales", finance: "Finance" }, can_edit,
});
const block = { raised: 4, closed: 2, open: 2, first_response_avg_h: 1.5, first_response_median_h: 1.2, resolution_avg_h: 20.5, resolution_median_h: 18, paused_customer_h: 3,
  paused_external_h: 0, response_breaches: 1, resolution_breaches: 1, at_risk_now: 1, escalated: { level1: 2, level2: 1, level3: 0 }, reopened: 1, csat_avg: 4.5,
  csat_responses: 2, csat_distribution: { "5": 1, "4": 1, "3": 0, "2": 0, "1": 0 } };

describe("service settings and reports", () => {
  it("CRM managers see the settings read-only", async () => {
    mockApi(makeUser("crm_manager"), { get: { "/service/settings": settings(false) } });
    renderApp("/service/settings");
    expect(await screen.findByText("Only an admin can change these settings.")).toBeInTheDocument();
    expect(screen.getByLabelText("Urgent: first response")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save settings" })).not.toBeInTheDocument();
  });

  it("an admin changes a target and a category rule", async () => {
    const { put } = mockApi(makeUser("admin"), { get: { "/service/settings": settings(true) }, put: { "/service/settings": settings(true) } });
    renderApp("/service/settings");
    const t = await screen.findByLabelText("Normal: resolution");
    await userEvent.clear(t); await userEvent.type(t, "48");
    await userEvent.click(screen.getByLabelText("Document download request: needs customer confirmation"));
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    const body = put.mock.calls[0][1] as { resolution_hours: Record<string, number>; categories: Record<string, { needs_confirmation: boolean }> };
    expect(body.resolution_hours.normal).toBe(48);
    expect(body.categories.document.needs_confirmation).toBe(true);
    expect(await screen.findByText(/Service settings saved/)).toBeInTheDocument();
  });

  it("reports show the summary and the breakdowns", async () => {
    mockApi(makeUser("crm_manager"), { get: { "/service/reports": { start: "2026-10-22", end: "2026-11-20", overall: block,
      by_category: { defect: { ...block, label: "Defect or warranty complaint" } }, by_team: { after_sales: { ...block, label: "After-sales" } } } } });
    renderApp("/service/reports");
    expect(await screen.findByText("Resolution breaches")).toBeInTheDocument();
    const figure = (label: string) => screen.getAllByText(label).find((el) => el.tagName === "DT")!.nextSibling;  // the summary figure, not a table heading
    expect(figure("Resolution breaches")).toHaveTextContent("1 (25%)");
    expect(figure("Reopened")).toHaveTextContent("1 (25%)");
    expect(screen.getByText("4.5 / 5")).toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "By category" })).getByRole("row", { name: /Defect or warranty complaint/ })).toHaveTextContent("3 h / 0 h");
    expect(screen.getByRole("region", { name: "More detail" })).toHaveTextContent("level 2 1");
  });

  it("a ticket shows its escalations", async () => {
    const sla = { response_due_at: "2026-11-20T08:00:00Z", resolution_due_at: "2026-11-21T06:00:00Z", first_response_at: "2026-11-20T06:00:00Z", response_breached: false,
      resolution_breached: true, at_risk: false, paused: false, paused_hours_customer: 0, paused_hours_external: 0 };
    mockApi(makeUser("crm_manager"), { get: { "/tickets/5": { id: 5, ticket_no: "TKT-00005", case_id: 4, case_code: "PSC-00004", customer: "Anita Desai", unit: "1114",
      category: "defect", category_label: "Defect or warranty complaint", subcategory: null, title: "Seepage", priority: "high", team: "after_sales", team_label: "After-sales",
      status: "in_progress", owner: null, created_at: "2026-11-20T05:00:00Z", closed_at: null, closure_reason: null, reopened_count: 0, csat: null, sla, description: "x",
      channel: "phone", raised_by: null, resolution: null, resolved_at: null, customer_confirmed: null, confirmed_at: null, csat_comment: null, needs_confirmation: true,
      reopen_days: 14, owners: [], timeline: [], attachments: [], can: {},
      escalations: [{ level: 1, rule: "At risk of missing the resolution target", recipients: ["Pooja Test"], at: "2026-11-21T01:00:00Z" },
        { level: 2, rule: "Resolution target breached", recipients: ["Meera Test"], at: "2026-11-21T06:15:00Z" }] } } });
    renderApp("/service/5");
    const esc = await screen.findByRole("region", { name: "Escalations" });
    expect(esc).toHaveTextContent("Level 2"); expect(esc).toHaveTextContent("Resolution target breached"); expect(esc).toHaveTextContent("told Meera Test");
  });
});
