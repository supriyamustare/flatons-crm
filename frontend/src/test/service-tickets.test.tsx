import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TicketDetail, TicketRow } from "../hooks/useTickets";
import type { CaseDetail } from "../hooks/usePostSales";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const sla = { response_due_at: "2026-11-20T08:00:00Z", resolution_due_at: "2026-11-23T06:00:00Z", first_response_at: null, response_breached: false,
  resolution_breached: false, at_risk: false, paused: false, paused_hours_customer: 0, paused_hours_external: 0 };
const row = (over: Partial<TicketRow>): TicketRow => ({ id: 5, ticket_no: "TKT-00005", case_id: 4, case_code: "PSC-00004", customer: "Anita Desai", unit: "1114",
  category: "defect", category_label: "Defect or warranty complaint", subcategory: null, title: "Seepage in bathroom wall", priority: "high", team: "after_sales",
  team_label: "After-sales", status: "acknowledged", owner: { id: 2, full_name: "Pooja Test", role: "postsales_exec" }, created_at: "2026-11-20T05:00:00Z",
  closed_at: null, closure_reason: null, reopened_count: 0, csat: null, sla, ...over });
const lists = { categories: { defect: "Defect or warranty complaint", payment: "Payment or ledger clarification" }, teams: { after_sales: "After-sales", finance: "Finance" } };
const detail = (over: Partial<TicketDetail>): TicketDetail => ({ ...row({}), description: "Water seeping near the shower", channel: "phone", raised_by: null, resolution: null,
  resolved_at: null, customer_confirmed: null, confirmed_at: null, csat_comment: null, needs_confirmation: true, reopen_days: 14, owners: [],
  timeline: [{ id: 1, kind: "raised", internal: false, text: "Water seeping near the shower", data: null, by: null, at: "2026-11-20T05:00:00Z" },
    { id: 2, kind: "note", internal: true, text: "Contractor says it's a plumbing joint", data: null, by: { id: 2, full_name: "Pooja Test", role: "postsales_exec" }, at: "2026-11-20T06:00:00Z" }],
  attachments: [], can: { work: true, propose: true, note: true, message: true, close: true }, ...over });

describe("service", () => {
  it("lists tickets with SLA badges and asks for the breached view", async () => {
    const { get } = mockApi(makeUser("crm_manager"), { get: { "/tickets": { items: [row({ sla: { ...sla, resolution_breached: true } }), row({ id: 6, ticket_no: "TKT-00006", sla: { ...sla, at_risk: true } })], ...lists } } });
    renderApp("/service");
    const table = await screen.findByRole("table", { name: "Tickets" });
    expect(await within(table).findByRole("row", { name: /TKT-00005/ })).toHaveTextContent("SLA breached");
    expect(within(table).getByRole("row", { name: /TKT-00006/ })).toHaveTextContent("At risk");
    await userEvent.click(screen.getByRole("tab", { name: "Breached" }));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/tickets", expect.objectContaining({ params: expect.objectContaining({ view: "breached" }) })));
  });

  it("the ticket page marks internal notes and shows the SLA", async () => {
    mockApi(makeUser("postsales_exec"), { get: { "/tickets/5": detail({}) } });
    renderApp("/service/5");
    const tl = await screen.findByRole("region", { name: "Timeline" });
    const note = within(tl).getByText("Contractor says it's a plumbing joint").closest("li")!;
    expect(note).toHaveTextContent("Internal");
    expect(within(tl).getByText("Water seeping near the shower").closest("li")).not.toHaveTextContent("Internal");
    expect(screen.getByRole("region", { name: "Service level" })).toHaveTextContent("Not yet responded");
  });

  it("waiting for the customer explains the pause", async () => {
    const { post } = mockApi(makeUser("postsales_exec"), { get: { "/tickets/5": detail({ status: "in_progress" }) }, post: { "/tickets/5/status": detail({ status: "waiting_customer" }) } });
    renderApp("/service/5");
    await userEvent.click(await screen.findByRole("button", { name: "Change status" }));
    const d = await screen.findByRole("dialog", { name: "Change status" });
    expect(d).toHaveTextContent("The resolution target is paused while waiting");
    expect(within(d).getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(within(d).getByLabelText("What or who is it waiting for?"), "Asked for photos of the wall");
    await userEvent.click(within(d).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/tickets/5/status", { status: "waiting_customer", note: "Asked for photos of the wall" }));
  });

  it("raising a ticket from the case opens it", async () => {
    const kase = { id: 4, case_code: "PSC-00004", status: "accepted", onboarding_status: "approved", customer: "Anita Desai", project: "Habitat", unit_no: "1114",
      booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-11-17", agreed_price: 3_225_000, owner: null, sales_exec: null, created_at: "2026-11-17T05:00:00Z",
      kyc_done: 4, kyc_total: 4, returned_reason: null, clarification_reason: null, accepted_at: "2026-11-17T05:00:00Z", handover: [], profile: null, co_applicants: [],
      requirements: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: false, history: [] } as unknown as CaseDetail;
    const { post } = mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/tickets": { items: [], ...lists }, "/tickets/5": detail({}) },
      post: { "/post-sales/cases/4/tickets": detail({}) } });
    renderApp("/post-sales/4?tab=service");
    const panel = await screen.findByRole("tabpanel", { name: "Service" });
    await userEvent.click(within(panel).getByRole("button", { name: "Raise ticket" }));
    const d = await screen.findByRole("dialog", { name: "Raise a ticket" });
    await userEvent.selectOptions(within(d).getByLabelText("Category"), "defect");
    await userEvent.type(within(d).getByLabelText("Title"), "Seepage in bathroom wall");
    await userEvent.type(within(d).getByLabelText("The customer’s issue or request"), "Water seeping near the shower");
    await userEvent.click(within(d).getByRole("button", { name: "Raise ticket" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect((post.mock.calls[0][1] as FormData).get("category")).toBe("defect");
    expect(await screen.findByRole("heading", { name: /TKT-00005: Seepage in bathroom wall/ })).toBeInTheDocument();
  });
});
