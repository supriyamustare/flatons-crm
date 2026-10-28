import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PriceAndArea, UnitCustomer, type CostSheet } from "../components/inventory/UnitSections";
import type { Booking } from "../lib/bookings";
import type { Unit } from "../lib/inventory";
import { makeUser, mockApi } from "./mockApi";
import { renderApp, renderWithProviders } from "./render";

const unit = (extra: Partial<Unit> = {}): Unit => ({
  id: 11, project_id: 1, building_id: 1, floor_id: 2, floor_number: 2, unit_no: "201", unit_type: "studio", carpet_sqft: "200.32",
  builtup_sqft: "290.46", base_price: null, current_asking_price: null, address_note: "Co-living Rooms (Room-1)", status: "available",
  hold_expired: false, held_by: null, held_for: null, held_at: null, hold_expires_at: null, hold_note: null, booking_id: null, rate_psf: null, ...extra,
});
const ravi = { id: 7, full_name: "Ravi Kumar", role: "executive" as const };

beforeEach(() => vi.restoreAllMocks());

describe("price and area", () => {
  it("managers enter area and rate; the price is worked out", async () => {
    const { patch } = mockApi(makeUser("manager"), { patch: { "/units/11": {} } });
    renderWithProviders(<PriceAndArea unit={unit()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.type(screen.getByLabelText("Rate per sq ft (₹)"), "14000");
    expect(screen.getByText(/Price: ₹40.66 L/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/units/11", { carpet_sqft: 200.32, builtup_sqft: 290.46, rate_psf: 14000 }));
  });

  it("executives can see but not edit", async () => {
    mockApi(makeUser("executive"));
    renderWithProviders(<PriceAndArea unit={unit({ rate_psf: "14000.00", current_asking_price: 4_066_440 })} />);
    expect(await screen.findByText("₹40.66 L")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });
});

describe("customer on the unit", () => {
  const booking = {
    id: 9, booking_code: "BKG-00009", status: "booked", sales_exec: ravi,
    customer: { customer_name: "Anita Desai", applicant_name: "Anita & Rohan Desai", customer_mobile: "+919876543210", customer_email: "anita@example.com",
      customer_address: "Flat 4, Baner Road, Pune", payment_preference: "bank", bank_name: "HDFC Bank", banker_name: "Suresh Iyer", banker_phone: "9822011111" },
  } as unknown as Booking;

  it("shows name, applicant, contact, address and bank payment details", async () => {
    mockApi(makeUser("manager"), { get: { "/bookings/9": booking } });
    renderWithProviders(<UnitCustomer unit={unit({ status: "booked", booking_id: 9 })} />);
    const s = await screen.findByRole("region", { name: "Customer" });
    await within(s).findByText("Anita Desai"); // the booking loads after the section appears
    for (const text of ["Anita Desai", "Anita & Rohan Desai", "anita@example.com", "Flat 4, Baner Road, Pune", "Bank payment (home loan)", "HDFC Bank"]) {
      expect(within(s).getByText(text)).toBeInTheDocument();
    }
    expect(within(s).getByText(/Contact: Suresh Iyer · 9822011111/)).toBeInTheDocument();
  });

  it("editing: bank fields appear only for bank payment, and are cleared for self payment", async () => {
    const { patch } = mockApi(makeUser("executive", { id: 7 }), { get: { "/bookings/9": booking }, patch: { "/bookings/9/customer": booking } });
    renderWithProviders(<UnitCustomer unit={unit({ status: "booked", booking_id: 9 })} />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Customer and payment" });
    expect(within(dialog).getByLabelText("Bank name")).toHaveValue("HDFC Bank");
    await userEvent.selectOptions(within(dialog).getByLabelText("Payment preference"), "self");
    expect(within(dialog).queryByLabelText("Bank name")).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/bookings/9/customer", expect.objectContaining({ payment_preference: "self", bank_name: null, banker_name: null })));
  });

  it("an available unit offers Book this unit, without asking for a booking", async () => {
    const { get } = mockApi(makeUser("executive"));
    renderWithProviders(<UnitCustomer unit={unit()} />);
    expect(await screen.findByRole("button", { name: "Book this unit" })).toBeInTheDocument();
    expect(get.mock.calls.map((c) => c[0])).not.toContain("/bookings/0");
  });
});

describe("printed cost sheet", () => {
  const sheet: CostSheet = {
    ready: true, missing: [], project: "Habitat", developer_name: "Avnee Estates", site_address: "Kharadi, Pune", rera_number: "",
    unit_no: "1008", unit_label: "Habitat / Floor 10 / Unit 1008 / Studio", carpet_sqft: 159.31, chargeable_sqft: 267.7, rate_psf: 14000,
    cost: 3_747_800, gst_pct: 1, gst: 37_478, stages: [{ name: "Booking", pct: 10, amount: 374_780, gst: 3_748 }, { name: "Plinth", pct: 90, amount: 3_373_020, gst: 33_730 }],
    furnishing_per_sqft: 413.79, furnishing: 110_772, stamp_duty_pct: 7, stamp_duty: 262_400, registration_pct: 1, registration_cap: 30000, registration: 30_000,
    legal_charges: 10_000, other_charges_label: "Other charges", other_charges: 0, fees_total: 302_400, grand_total: 4_198_450,
    notes: ["Prices are subject to change without prior notice."], signatory: "Avnee representative", overrides: {},
    customer: { name: "Anita Desai", applicant_name: "Anita & Rohan Desai", mobile: "+919876543210", email: null, address: "Baner, Pune",
      booking_code: "BKG-00009", booking_date: "2026-10-27", payment_preference: "bank", bank_name: "HDFC Bank" },
  };

  it("lays out the developer's cost sheet with totals, customer and notes", async () => {
    mockApi(makeUser("docs"), { get: { "/units/11/cost-sheet": sheet } });
    renderApp("/cost-sheet/11");
    const page = await screen.findByRole("article", { name: "Cost sheet" });
    for (const text of ["HABITAT", "AVNEE ESTATES", "₹ 37,47,800", "₹ 37,478", "₹ 2,62,400", "₹ 30,000", "₹ 3,02,400", "₹ 41,98,450", "Avnee representative"]) {
      expect(within(page).getAllByText(text).length).toBeGreaterThan(0);
    }
    expect(within(page).getByText("Anita & Rohan Desai")).toBeInTheDocument();
    expect(within(page).getByText(/Bank payment \(home loan\): HDFC Bank/)).toBeInTheDocument();
    expect(within(page).getByText("Prices are subject to change without prior notice.")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument(); // printable: no menu
    expect(screen.getByRole("button", { name: "Print" })).toBeInTheDocument();
  });
});

describe("lead sources in use", () => {
  it("a new lead offers only the sources in use", async () => {
    mockApi(makeUser("executive"), { get: { "/projects": [], "/campaigns": [] } });
    renderApp("/leads/new");
    const source = await screen.findByLabelText("Source", { exact: true }, { timeout: 4000 });
    const options = within(source).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(expect.arrayContaining(["99acres", "MagicBricks", "Housing.com", "Meta ads (Facebook / Instagram)", "Google Ads"]));
    expect(options.join(",")).not.toMatch(/Website/);
  });
});
