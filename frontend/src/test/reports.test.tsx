import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatRate } from "../lib/reports";
import type { CampaignsReport, CallsReport } from "../lib/reports";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

const defs = { "Cost per lead": "Spend ÷ leads attributed to this campaign." };
const calls: CallsReport = {
  date_from: "2026-09-27", date_to: "2026-10-26", scope: "team", definitions: { Calls: "Calls logged in the period." },
  rows: [{ user: { id: 7, full_name: "Ravi Kumar", role: "executive" }, calls: 12, connected: 5, connection_rate: 0.4167, talk_minutes: 31 }],
  totals: { user: null, calls: 12, connected: 5, connection_rate: 0.4167, talk_minutes: 31 },
  by_day: [{ day: "2026-10-25", calls: 4, connected: 2 }, { day: "2026-10-26", calls: 8, connected: 3 }],
};
const campaigns: CampaignsReport = {
  date_from: "2026-09-27", date_to: "2026-10-26", scope: "team", definitions: defs, unattributed_leads: 9,
  rows: [
    { campaign_id: 1, name: "Google Ads", channel: "google_ads", spend: 200000, leads: 10, visited: 4, booked: 1, cost_per_lead: 20000, cost_per_visit: 50000, cost_per_booking: 200000 },
    { campaign_id: 2, name: "Property expo stall", channel: "event", spend: 85000, leads: 0, visited: 0, booked: 0, cost_per_lead: null, cost_per_visit: null, cost_per_booking: null },
  ],
  totals: { campaign_id: null, name: "All campaigns", channel: null, spend: 285000, leads: 10, visited: 4, booked: 1, cost_per_lead: 28500, cost_per_visit: 71250, cost_per_booking: 285000 },
};

beforeEach(() => vi.restoreAllMocks());

describe("reports", () => {
  it("shows N/A rather than 0% when there is nothing to divide by", () => {
    expect(formatRate(null)).toBe("N/A");
    expect(formatRate(0)).toBe("0%");
    expect(formatRate(0.3684)).toBe("37%");
  });

  it("shows campaign costs with N/A for a campaign with no leads, and offers CSV to managers", async () => {
    mockApi(makeUser("manager"), { get: { "/reports/calls": calls, "/reports/campaigns": campaigns } });
    renderApp("/reports");
    await userEvent.click(await screen.findByRole("tab", { name: "Campaigns" }));
    const table = await screen.findByRole("table", { name: "By campaign" });
    const expo = within(table).getByRole("row", { name: /Property expo stall/ });
    expect(within(expo).getAllByText("N/A")).toHaveLength(3);
    expect(within(table).getByRole("row", { name: /All campaigns/ })).toHaveTextContent("₹28,500");
    expect(screen.getByRole("link", { name: "Download CSV" })).toHaveAttribute("href", expect.stringContaining("/api/reports/campaigns/export?range=30d"));
  });

  it("executives get their own reports, no Campaigns tab and no CSV", async () => {
    mockApi(makeUser("executive"), { get: { "/reports/calls": { ...calls, scope: "mine" } } });
    renderApp("/reports");
    expect(await screen.findByText(/your own figures/)).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Campaigns" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Download CSV" })).not.toBeInTheDocument();
    expect(screen.getByRole("table", { name: "By person" })).toHaveTextContent("42%");
  });

  it("explains how figures are calculated", async () => {
    mockApi(makeUser("admin"), { get: { "/reports/calls": calls } });
    renderApp("/reports");
    await userEvent.click(await screen.findByText("How these are calculated"));
    expect(screen.getByText("Calls logged in the period.")).toBeInTheDocument();
  });
});

describe("marketing", () => {
  it("is for admins and managers only", async () => {
    mockApi(makeUser("executive"));
    renderApp("/marketing");
    expect(await screen.findByText("You don’t have access to this page")).toBeInTheDocument();
  });

  it("sends an expense with its receipt as a form upload", async () => {
    const camp = { id: 1, name: "Google Ads", channel: "google_ads", project: null, start_date: "2026-10-01", end_date: null, description: null, created_at: "2026-10-01T00:00:00Z" };
    const page = { items: [], total: 0, page: 1, page_size: 50, total_amount: 0, by_channel: {} };
    const { post } = mockApi(makeUser("manager"), {
      get: { "/campaigns": [camp], "/expenses": page, "/reports/campaigns": campaigns },
      post: { "/expenses": { id: 9 } },
    });
    renderApp("/marketing");
    await userEvent.click(await screen.findByRole("tab", { name: "Expenses" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add expense" }));
    const dialog = await screen.findByRole("dialog", { name: "Add expense" });
    await userEvent.selectOptions(within(dialog).getByLabelText("Campaign"), "1");
    await userEvent.type(within(dialog).getByLabelText("Amount (₹)"), "45000");
    const file = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "invoice.png", { type: "image/png" });
    await userEvent.upload(within(dialog).getByLabelText("Receipt (optional)"), file);
    await userEvent.click(within(dialog).getByRole("button", { name: "Save expense" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0] as [string, FormData];
    expect(url).toBe("/expenses");
    expect(body.get("amount")).toBe("45000");
    expect((body.get("receipt") as File).name).toBe("invoice.png");
  });
});
