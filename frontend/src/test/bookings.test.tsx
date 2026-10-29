import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Booking, BookingPage } from "../lib/bookings";
import type { Insights } from "../hooks/useInsights";
import type { Inventory, Unit } from "../lib/inventory";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

const ravi = { id: 7, full_name: "Ravi Kumar", role: "executive" as const };
const unit = (id: number, unit_no: string, extra: Partial<Unit> = {}): Unit => ({
  id, project_id: 1, building_id: 1, floor_id: 2, floor_number: 2, unit_no, unit_type: "2bhk", carpet_sqft: "680", builtup_sqft: "890",
  base_price: 7_000_000, current_asking_price: 7_400_000, address_note: null, status: "available", hold_expired: false,
  held_by: null, held_for: null, held_at: null, hold_expires_at: null, hold_note: null, booking_id: null, ...extra,
});
const project = { id: 1, name: "Green Meadows", is_active: true, project_type: "developer", status: "under_construction",
  developer: { id: 1, name: "Skyline" }, location: "Baner", description: null, commission_pct: "2.00", created_at: "2026-10-01T00:00:00Z" };
const inventory = {
  project, counts: {}, listings: [],
  buildings: [{ id: 1, name: "A Wing", sort_order: 0, counts: {}, floors: [{ id: 2, number: 2, units: [
    unit(201, "201"), unit(202, "202", { status: "booked", booking_id: 9 }), unit(203, "203", { status: "on_hold", held_for: { id: 5, name: "Anita Desai", lead_code: "L-5" } }),
    unit(204, "204", { status: "on_hold", held_for: { id: 6, name: "Someone else", lead_code: "L-6" } }),
  ] }] }],
} as unknown as Inventory;
const booking: Booking = {
  id: 9, booking_code: "BKG-00009", status: "booked",
  lead: { id: 5, lead_code: "L-5", name: "Anita Desai", mobile: "+919876543210", email: null, city: "Baner" },
  project: { id: 1, name: "Green Meadows" },
  unit: { id: 201, unit_no: "201", unit_type: "2bhk", building: "A Wing", floor_number: 2, carpet_sqft: "680", builtup_sqft: "890", address_note: null },
  booking_date: "2026-10-27", agreement_date: null, agreed_price: 7_200_000, booking_amount: 200_000, balance: 7_000_000, payment_mode: "cheque", payment_reference: "CHQ 4512",
  channel_partner: null, commission_pct: "2.00", commission_expected: 144_000, commission_received: 0, notes: null, sales_exec: ravi, recorded_by: ravi,
  customer: { customer_name: "Anita Desai", applicant_name: "Anita & Rohan Desai", customer_mobile: "+919876543210", customer_email: null,
    customer_address: "Baner, Pune", payment_preference: "bank", bank_name: "HDFC Bank", banker_name: "Suresh Iyer", banker_phone: "9822011111" },
  created_at: "2026-10-27T08:00:00Z", cancelled_at: null, cancellation_reason: null,
  history: [{ at: "2026-10-27T08:00:00Z", action: "created", actor: ravi, details: {} }],
};
const leadDetail = { id: 5, lead_code: "L-5", name: "Anita Desai", mobile: "+919876543210", alt_mobile: null, email: null, city: "Baner", locality: null,
  source: "website", sub_source: null, status: "negotiation", project: { id: 1, name: "Green Meadows" }, campaign: null, configuration: null, purpose: null,
  budget_min: null, budget_max: null, buying_timeline: null, remarks: null, lost_reason: null, estimated_value: null, assigned_to: ravi, created_by: ravi,
  created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-27T00:00:00Z", last_activity_at: "2026-10-27T00:00:00Z", activities: [], can_edit: true, booking: null };

beforeEach(() => vi.restoreAllMocks());

describe("book a flat", () => {
  it("offers only bookable flats, previews balance and commission, and records the booking", async () => {
    const { post } = mockApi(makeUser("executive", { id: 7, full_name: "Ravi Kumar" }), {
      get: { "/leads/5": leadDetail, "/leads/5/tasks": [], "/leads/5/visits": [], "/projects": [project], "/projects/1/inventory": inventory, "/bookings/9": booking },
      post: { "/bookings": booking },
    });
    renderApp("/leads/5");
    await userEvent.click(await screen.findByRole("button", { name: "Book a flat" }, { timeout: 4000 }));
    const dialog = await screen.findByRole("dialog", { name: "Book a flat for Anita Desai" });
    const flat = await within(dialog).findByLabelText("Flat");
    await waitFor(() => expect(within(flat).getAllByRole("option")).toHaveLength(3)); // placeholder + 201 + 203 (held for her)
    expect(within(flat).queryByRole("option", { name: /Unit 202/ })).not.toBeInTheDocument();
    expect(within(flat).queryByRole("option", { name: /Unit 204/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(flat, "201");
    const price = within(dialog).getByLabelText("Agreed price (₹)");
    expect(price).toHaveValue("7400000"); // pre-filled from the asking price
    await userEvent.clear(price);
    await userEvent.type(price, "7200000");
    await userEvent.type(within(dialog).getByLabelText("Booking amount paid (₹)"), "200000");
    expect(dialog).toHaveTextContent("Balance ₹70 L");
    expect(dialog).toHaveTextContent("Flatons commission (2%) ≈ ₹1.44 L");
    await userEvent.click(within(dialog).getByRole("button", { name: "Record booking" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/bookings", expect.objectContaining({ lead_id: 5, unit_id: 201, agreed_price: 7_200_000, booking_amount: 200_000 })));
    expect(await screen.findByRole("heading", { name: "BKG-00009: Anita Desai" })).toBeInTheDocument();
  });

  it("a booked lead shows its booking instead of the button", async () => {
    mockApi(makeUser("executive", { id: 7 }), { get: { "/leads/5": { ...leadDetail, status: "booked",
      booking: { id: 9, booking_code: "BKG-00009", project: "Green Meadows", unit_no: "201", agreed_price: 7_200_000 } }, "/leads/5/tasks": [], "/leads/5/visits": [] } });
    renderApp("/leads/5");
    expect(await screen.findByRole("link", { name: /Booked: Green Meadows, unit 201 for ₹72 L/ })).toHaveAttribute("href", "/bookings/9");
    expect(screen.queryByRole("button", { name: "Book a flat" })).not.toBeInTheDocument();
  });
});

describe("bookings list and detail", () => {
  const page: BookingPage = { items: [booking], total: 1, page: 1, page_size: 50,
    totals: { count: 1, agreed_value: 7_200_000, booking_amount: 200_000, commission_expected: 144_000, commission_received: 0 },
    missing_details: [{ lead_id: 3, lead_code: "L-3", name: "Old Booking", mobile: "+919000000001", project: null, assigned_to: ravi, booked_since: "2026-09-01T00:00:00Z" }] };

  it("managers see totals, details missing, and can download CSV", async () => {
    mockApi(makeUser("manager"), { get: { "/bookings": page, "/projects": [project], "/users/assignable": [ravi] } });
    renderApp("/bookings");
    expect(await screen.findByRole("heading", { name: "Details missing (1)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add booking details" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Totals" })).toHaveTextContent("₹72 L");
    expect(screen.getByRole("link", { name: "BKG-00009" })).toHaveAttribute("href", "/bookings/9");
    expect(screen.getByRole("link", { name: "Download CSV" })).toBeInTheDocument();
  });

  it("executives get no CSV; documents staff can view but not add details", async () => {
    mockApi(makeUser("docs"), { get: { "/bookings": page, "/projects": [project] } });
    renderApp("/bookings");
    expect(await screen.findByRole("link", { name: "BKG-00009" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add booking details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Download CSV" })).not.toBeInTheDocument();
  });

  it("cancelling needs a reason and is for managers", async () => {
    const { post } = mockApi(makeUser("manager"), { get: { "/bookings/9": booking }, post: { "/bookings/9/cancel": { ...booking, status: "cancelled" } } });
    renderApp("/bookings/9");
    await userEvent.click(await screen.findByRole("button", { name: "Cancel booking" }));
    const dialog = await screen.findByRole("dialog", { name: "Cancel BKG-00009?" });
    expect(within(dialog).getByRole("button", { name: "Cancel booking" })).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Reason"), "Loan not approved");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel booking" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/bookings/9/cancel", { reason: "Loan not approved" }));
  });

  it("executives can't edit or cancel", async () => {
    mockApi(makeUser("executive", { id: 7 }), { get: { "/bookings/9": booking } });
    renderApp("/bookings/9");
    expect(await screen.findByText("Commission expected")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel booking" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit details" })).not.toBeInTheDocument();
  });
});

describe("dashboard insights", () => {
  const ins: Insights = {
    projects: [{ id: 1, name: "Green Meadows", location: "Baner", project_type: "developer", unit_types: ["2bhk", "3bhk"], price_min: 6_500_000,
      price_max: 9_500_000, sold: 13, agreement_done: 4, booked: 9, blocked: 9, available: 78, total: 100, sold_pct: 13, bookings_this_month: 2, booked_value_this_month: 15_000_000 }],
    lead_status: [{ key: "working", count: 40 }, { key: "quiet", count: 30 }, { key: "unassigned", count: 5 }, { key: "booked", count: 5 }, { key: "dead", count: 20 }],
    total_leads: 100, waiting_by_owner: [{ user: ravi, count: 4 }, { user: null, count: 2 }],
    scheduled_30d: [{ key: "site_visit", count: 4 }, { key: "call", count: 12 }],
    months: Array.from({ length: 12 }, (_, i) => ({ month: `2026-${String(i + 1).padStart(2, "0")}-01`, leads: i === 8 ? 90 : 10, deals: i })),
    sources: [{ source: "website", leads: 11, sales: 1, conversion: 9.1 }, { source: "referral", leads: 0, sales: 0, conversion: null }],
    first_response_min: 75, contacted_within_day_pct: 80, recent_bookings: [{ id: 9, booking_code: "BKG-00009", customer: "Anita Desai", project: "Green Meadows",
      unit_no: "201", agreed_price: 7_200_000, booking_date: "2026-10-27", sales_exec: ravi }],
  };

  it("shows projects, lead status, first contact, months, sources and recent bookings", async () => {
    const { get } = mockApi(makeUser("manager"), { get: { "/dashboard/insights": ins } });
    renderApp("/");
    expect(await screen.findByRole("img", { name: "Green Meadows: 4 agreement done, 9 booked, 9 on hold, 78 available of 100" })).toBeInTheDocument();
    expect(screen.getByText("13% booked")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Lead status" })).toHaveTextContent("Gone quiet30");
    expect(screen.getByText(/Median first response this month:/)).toHaveTextContent("1 h 15 min · 80% called within a day");
    expect(screen.getByText(/^Peak 90 in Sept?$/)).toBeInTheDocument(); // Indian English writes "Sept"
    expect(within(screen.getByRole("region", { name: "Source performance" })).getByText("N/A")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Recent bookings" })).getByRole("link", { name: /Anita Desai/ })).toHaveAttribute("href", "/bookings/9");
    expect(get).toHaveBeenCalledWith("/dashboard/insights", { params: { person_id: undefined } });
  });
});
