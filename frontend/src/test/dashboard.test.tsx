import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Dashboard } from "../hooks/useDashboard";
import { taskTypeInSentence } from "../lib/tasks";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

const leadRef = { id: 11, lead_code: "LEAD-1", name: "Anita Desai", mobile: "+919876543210" };

function dash(overrides: Partial<Dashboard["kpis"]> = {}, extra: Partial<Dashboard> = {}): Dashboard {
  return {
    scope: "team", date_from: "2026-10-17", date_to: "2026-10-23",
    kpis: { total_leads: 60, new_leads: 12, follow_ups_today: 15, overdue_follow_ups: 20, visits_scheduled: 8,
      visits_completed: 5, calls: 38, calls_connected: 14, connection_rate: 0.3684, ...overrides },
    leads_by_status: { new: 13, not_reachable: 0, contacted: 6, qualified: 0, follow_up: 0, visit_scheduled: 0, visit_done: 0,
      revisit: 0, negotiation: 0, on_hold: 0, booked: 4, lost: 0, junk: 0 },
    overdue: [{ id: 1, lead: leadRef, task_type: "whatsapp", due_at: "2026-10-20T08:39:00Z", status: "pending", is_overdue: true,
      notes: null, completion_note: null, completed_at: null, rescheduled_from_id: null, reschedule_reason: null,
      assigned_to: { id: 7, full_name: "Ravi Kumar", role: "executive" }, created_by: null, created_at: "2026-10-19T08:00:00Z" }],
    visits_needing_update: [],
    activity: [{ id: 5, type: "call_logged", note: null, details: { outcome: "busy", direction: "outgoing" },
      actor: { id: 7, full_name: "Ravi Kumar", role: "executive" }, lead_id: 11, lead_name: "Anita Desai", lead_code: "LEAD-1",
      created_at: "2026-10-23T06:00:00Z" }],
    business: null,
    team: null,
    ...extra,
  };
}

beforeEach(() => vi.restoreAllMocks());

describe("dashboard", () => {
  it("shows the team's numbers, alerts and activity to an admin", async () => {
    mockApi(makeUser("admin", { full_name: "Supriya Mustare" }), { get: { "/dashboard/admin": dash() } });
    renderApp("/");

    const kpis = await screen.findByRole("region", { name: "Key numbers" });
    expect(within(kpis).getByRole("link", { name: "Overdue follow-ups: 20" })).toHaveAttribute("href", "/follow-ups");
    expect(within(kpis).getByText("14 connected (37%)")).toBeInTheDocument();
    expect(screen.getByText(/WhatsApp with/)).toBeInTheDocument();
    expect(screen.getByText("Busy")).toBeInTheDocument();
  });

  it("shows N/A for the connection rate when there were no calls", async () => {
    mockApi(makeUser("executive"), {
      get: { "/dashboard/executive": dash({ calls: 0, calls_connected: 0, connection_rate: null }, { scope: "mine" }) },
    });
    renderApp("/");
    expect(await screen.findByText("Connection rate: N/A")).toBeInTheDocument();
  });

  it("asks executives for their own numbers and managers can switch to Mine", async () => {
    const exec = mockApi(makeUser("executive"), { get: { "/dashboard/executive": dash({}, { scope: "mine" }) } });
    renderApp("/");
    await screen.findByRole("region", { name: "Key numbers" });
    expect(exec.get).toHaveBeenCalledWith("/dashboard/executive", { params: { range: "7d" } });
    expect(screen.queryByRole("group", { name: "Whose numbers" })).not.toBeInTheDocument();
  });

  it("invites the first lead when there are none", async () => {
    mockApi(makeUser("manager"), { get: { "/dashboard/admin": dash({ total_leads: 0 }, { activity: [], overdue: [] }) } });
    renderApp("/");
    expect(await screen.findByRole("link", { name: "Add a lead" })).toHaveAttribute("href", "/leads/new");
  });

  it("waits for both dates before loading a custom range", async () => {
    const m = mockApi(makeUser("admin"), { get: { "/dashboard/admin": dash() } });
    renderApp("/");
    await screen.findByRole("region", { name: "Key numbers" });
    await userEvent.click(screen.getByRole("button", { name: "Custom" }));
    expect(screen.getByText("Choose a start and end date.")).toBeInTheDocument();
    expect(m.get).not.toHaveBeenCalledWith("/dashboard/admin", { params: expect.objectContaining({ range: "custom" }) });
  });

  it("gives documents staff a simple page without sales numbers", async () => {
    mockApi(makeUser("docs"));
    renderApp("/");
    expect(await screen.findByText(/look up any lead/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Key numbers" })).not.toBeInTheDocument();
  });

  it("writes task types naturally mid-sentence", () => {
    expect(taskTypeInSentence("whatsapp")).toBe("WhatsApp");
    expect(taskTypeInSentence("site_visit")).toBe("site visit");
  });
});

describe("business figures (manager's Team view)", () => {
  const business = { leads_generated: 40, leads_booked: 3, booking_rate: 0.075, revenue: 160_000, expense: 200_000, profit: -40_000, unvalued_bookings: 2 };

  it("shows leads generated, booked, revenue, expense and a loss in red", async () => {
    mockApi(makeUser("manager"), { get: { "/dashboard/admin": dash({}, { business }) } });
    renderApp("/");
    const section = await screen.findByRole("region", { name: "Business" });
    expect(within(section).getByRole("link", { name: "Leads generated: 40" })).toBeInTheDocument();
    expect(within(section).getByRole("link", { name: "Leads booked: 3, 8% of leads generated" })).toBeInTheDocument();
    expect(within(section).getByLabelText(/^Commission revenue: ₹1\.6 L/)).toBeInTheDocument();
    expect(within(section).getByLabelText(/^Estimated loss: −₹40,000/)).toBeInTheDocument();
    expect(within(section).getByText(/2 booked leads aren’t counted in revenue/)).toBeInTheDocument();
  });

  it("calls a positive result a profit", async () => {
    mockApi(makeUser("admin"), { get: { "/dashboard/admin": dash({}, { business: { ...business, revenue: 500_000, profit: 300_000, unvalued_bookings: 0 } }) } });
    renderApp("/");
    const section = await screen.findByRole("region", { name: "Business" });
    expect(within(section).getByLabelText(/^Estimated profit: ₹3 L/)).toBeInTheDocument();
    expect(within(section).queryByText(/aren’t counted/)).not.toBeInTheDocument();
  });

  it("isn't shown on an executive's dashboard", async () => {
    mockApi(makeUser("executive"), { get: { "/dashboard/executive": dash({}, { scope: "mine", business: null }) } });
    renderApp("/");
    await screen.findByRole("region", { name: "Key numbers" });
    expect(screen.queryByRole("region", { name: "Business" })).not.toBeInTheDocument();
  });
});


describe("team performance (manager's Team view)", () => {
  const member = (id: number, name: string, extra = {}) => ({
    user: { id, full_name: name, role: "executive" as const }, calls_today: 12, calls: 40, connected: 18, connection_rate: 0.45,
    visits_done: 3, converted: 2, dead: 1, closing_rate: 0.6667, open_leads: 14, overdue: 0, ...extra,
  });

  it("shows each person's calls today, conversions, dead leads and closing rate", async () => {
    const team = [member(7, "Ravi Kumar"), member(8, "Kiran Rao", { calls_today: 0, converted: 0, dead: 0, closing_rate: null, overdue: 4 })];
    mockApi(makeUser("manager"), { get: { "/dashboard/admin": dash({}, { team }) } });
    renderApp("/");
    const table = await screen.findByRole("table", { name: "Team performance" });
    const ravi = within(table).getByRole("row", { name: /Ravi Kumar/ });
    expect(within(ravi).getAllByRole("cell").map((c) => c.textContent)).toEqual(["12", "40", "18 (45%)", "3", "2", "1", "67%", "14", "0"]);
    const kiran = within(table).getByRole("row", { name: /Kiran Rao/ });
    expect(within(kiran).getAllByRole("cell")[6]).toHaveTextContent("N/A");
    expect(within(table).getByRole("link", { name: "Ravi Kumar" })).toHaveAttribute("href", "/reports?report=staff&person=7");
  });

  it("isn't on an executive's dashboard", async () => {
    mockApi(makeUser("executive"), { get: { "/dashboard/executive": dash({}, { scope: "mine", team: null }) } });
    renderApp("/");
    await screen.findByRole("region", { name: "Key numbers" });
    expect(screen.queryByRole("heading", { name: "Team performance" })).not.toBeInTheDocument();
  });

  it("the link opens that person's staff report", async () => {
    const { get } = mockApi(makeUser("manager"), { get: { "/reports/staff": { date_from: "2026-09-28", date_to: "2026-10-27", scope: "person",
      definitions: {}, rows: [], totals: { user: { id: 0, full_name: "Everyone", role: "executive" }, leads: 0, calls: 0, connected: 0,
      connection_rate: null, visits_completed: 0, bookings: 0, lead_to_booking_rate: null } } } });
    renderApp("/reports?report=staff&person=7");
    expect(await screen.findByRole("tab", { name: "Staff" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(get).toHaveBeenCalledWith("/reports/staff", { params: expect.objectContaining({ user_id: 7 }) }));
  });
});
