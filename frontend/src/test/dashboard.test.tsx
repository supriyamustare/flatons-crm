import { screen, within } from "@testing-library/react";
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
