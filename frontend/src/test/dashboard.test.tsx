import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Dashboard } from "../hooks/useDashboard";
import type { Overview } from "../hooks/useOverview";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

const trend = (month: number, last_month: number, change_pct: number | null) => ({ month, last_month, change_pct, daily: Array(30).fill(1) });
const people = [{ id: 7, full_name: "Ravi Kumar", role: "executive" as const }, { id: 8, full_name: "Kiran Rao", role: "executive" as const }];

function overview(extra: Partial<Overview> = {}): Overview {
  return {
    scope: "team", person: null, today: "2026-10-27",
    in_closing: 17, fresh_waiting: 173, followups_due: 172, followups_overdue: 40, visits_today: 2,
    visits_completed: { week: 4, month: 38 }, sales_closed: { week: 0, month: 8 }, sales_revenue: { week: 0, month: 73_000_000 },
    performance: { enquiries: trend(93, 37, 151.4), site_visits: trend(38, 0, null), sales: trend(8, 4, 100), calls: trend(400, 500, -20),
      spend: trend(170_000, 80_000, 112.5), cost_per_sale: 21_250 },
    tab_counts: { fresh: 173, today: 3, visit: 4, closing: 17, reengage: 22 }, tab: "fresh",
    leads: [{ id: 1, lead_code: "L-1", name: "Anita Desai", mobile: "+919876543210", source: "google_ads", status: "new", city: "Baner",
      next_action: "Follow-up", next_at: "2026-10-27T12:30:00Z", owner: people[0] }],
    this_month: { new_leads: 93, active: 98, qualified: 61, unassigned: 5, active_rate: 0.091, win_rate: 0.25 },
    people, ...extra,
  };
}

function dash(extra: Partial<Dashboard> = {}): Dashboard {
  return { scope: "team", range: "30d", date_from: "2026-09-28", date_to: "2026-10-27", activity: [], business: null, team: null, ...extra } as unknown as Dashboard;
}

beforeEach(() => vi.restoreAllMocks());

describe("dashboard overview", () => {
  it("summarises the day and links the tiles to their lists", async () => {
    mockApi(makeUser("manager"), { get: { "/dashboard/overview": overview(), "/dashboard/admin": dash() } });
    renderApp("/");
    expect(await screen.findByText("Day 27 of October: 17 deals are in closing and 173 fresh leads are waiting on first contact.")).toBeInTheDocument();
    const today = screen.getByRole("region", { name: "Today" });
    expect(within(today).getByRole("link", { name: "Follow-ups due: 172, 40 overdue" })).toHaveAttribute("href", "/follow-ups");
    expect(within(today).getByRole("link", { name: "Visits today: 2" })).toHaveAttribute("href", "/visits");
    expect(within(today).getByRole("link", { name: "In closing: 17" })).toHaveAttribute("href", "/pipeline");
    const strip = screen.getByRole("region", { name: "This week and this month" });
    expect(strip).toHaveTextContent("Sales closed");
    expect(strip).toHaveTextContent("₹7.3 Cr");
  });

  it("shows change against the same days last month, and 'new' when there was nothing", async () => {
    mockApi(makeUser("manager"), { get: { "/dashboard/overview": overview(), "/dashboard/admin": dash() } });
    renderApp("/");
    const perf = await screen.findByRole("heading", { name: "Performance" });
    const section = perf.closest("section")!;
    expect(within(section).getByText(/\+151\.4%/)).toBeInTheDocument();
    expect(within(section).getByText("new")).toBeInTheDocument();
    expect(within(section).getByText(/cost per sale ₹21,250/)).toBeInTheDocument();
  });

  it("switches the lead list tabs", async () => {
    const { get } = mockApi(makeUser("manager"), { get: { "/dashboard/overview": overview(), "/dashboard/admin": dash() } });
    renderApp("/");
    const table = await screen.findByRole("table", { name: "Leads to work on" });
    expect(within(table).getByRole("link", { name: "Anita Desai" })).toHaveAttribute("href", "/leads/1");
    await userEvent.click(screen.getByRole("tab", { name: /Re-engage/ }));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/dashboard/overview", { params: { person_id: undefined, tab: "reengage" } }));
  });

  it("lets a manager pick one person", async () => {
    const { get } = mockApi(makeUser("manager"), { get: { "/dashboard/overview": overview(), "/dashboard/admin": dash() } });
    renderApp("/");
    const picker = await screen.findByRole("group", { name: "Show figures for" });
    expect(within(picker).getByRole("button", { name: "All team" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(picker).getByRole("button", { name: "Ravi" }));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/dashboard/overview", { params: { person_id: 7, tab: "fresh" } }));
  });

  it("shows business and team performance for managers", async () => {
    const team = [{ user: people[0], calls_today: 12, calls: 40, connected: 18, connection_rate: 0.45, visits_done: 3, converted: 2, dead: 1,
      closing_rate: 0.6667, open_leads: 14, overdue: 0 }];
    const business = { leads_generated: 46, leads_booked: 2, booking_rate: 0.04, revenue: 308_000, expense: 470_000, profit: -162_000, unvalued_bookings: 0 };
    mockApi(makeUser("manager"), { get: { "/dashboard/overview": overview(), "/dashboard/admin": dash({ business, team }) } });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Business and team" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Business" })).toHaveTextContent("Estimated loss");
    expect(within(await screen.findByRole("table", { name: "Team performance" })).getByRole("row", { name: /Ravi Kumar/ })).toHaveTextContent("67%");
  });

  it("executives see their own figures, with no picker and no business section", async () => {
    const mine = overview({ scope: "person", person: people[0], people: [],
      performance: { ...overview().performance, spend: null, cost_per_sale: null } });
    mockApi(makeUser("executive"), { get: { "/dashboard/overview": mine, "/dashboard/executive": dash({ scope: "mine" }) } });
    renderApp("/");
    const perf = (await screen.findByRole("heading", { name: "Performance: Ravi Kumar" })).closest("section")!;
    expect(within(perf).getByText("Calls")).toBeInTheDocument();
    expect(within(perf).queryByText("Marketing spend")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Show figures for" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Business and team" })).not.toBeInTheDocument();
  });

  it("documents staff get a simple page", async () => {
    mockApi(makeUser("docs"));
    renderApp("/");
    expect(await screen.findByText(/look up any lead/)).toBeInTheDocument();
  });
});

describe("header search", () => {
  it("Ctrl+K focuses it, and Enter opens Leads with the search filled in", async () => {
    const page = { items: [], total: 0, page: 1, page_size: 25 };
    const { post } = mockApi(makeUser("executive"), {
      get: { "/dashboard/overview": overview({ scope: "person", person: people[0], people: [] }), "/dashboard/executive": dash({ scope: "mine" }), "/projects": [] },
      post: { "/leads/search": page },
    });
    renderApp("/");
    const box = await screen.findByLabelText("Search leads by name, mobile or lead ID");
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(box).toHaveFocus();
    await userEvent.type(box, "98765{Enter}");
    await waitFor(() => expect(post).toHaveBeenCalledWith("/leads/search", expect.objectContaining({ q: "98765" })));
    expect(window.location.search).toBe("");
  });
});
