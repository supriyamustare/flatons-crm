import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Inventory, Unit } from "../lib/inventory";
import { unitSpokenLabel } from "../lib/inventory";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

function unit(no: string, overrides: Partial<Unit> = {}): Unit {
  return {
    id: Number(no), project_id: 1, building_id: 1, floor_id: Number(no[0]), floor_number: Number(no[0]), unit_no: no,
    unit_type: "2bhk", carpet_sqft: "680.00", builtup_sqft: "890.00", base_price: 7200000, current_asking_price: 7200000,
    address_note: null, status: "available", hold_expired: false, held_by: null, held_for: null, held_at: null,
    hold_expires_at: null, hold_note: null, ...overrides,
  };
}

const counts = { total: 4, available: 2, on_hold: 1, booked: 0, sold: 1, withdrawn: 0 };
function inventory(units: Unit[]): Inventory {
  return {
    project: { id: 1, name: "Green Meadows", is_active: true, project_type: "developer", status: "under_construction",
      developer: { id: 1, name: "Skyline Developers" }, location: "Baner", description: null, commission_pct: "2.00", created_at: "2026-10-23T00:00:00Z" },
    counts,
    buildings: [{ id: 1, name: "A Wing", sort_order: 0, counts, floors: [
      { id: 2, number: 2, units: units.filter((u) => u.floor_number === 2) },
      { id: 1, number: 1, units: units.filter((u) => u.floor_number === 1) },
    ] }],
    listings: [],
  };
}

const held = unit("102", { status: "on_hold", held_by: { id: 3, full_name: "Meera Shah", role: "manager" },
  hold_expires_at: "2026-10-25T10:00:00Z", held_for: { id: 9, name: "Anita Desai", lead_code: "LEAD-1" } });
const units = [unit("101"), held, unit("201", { status: "sold" }), unit("202")];

beforeEach(() => vi.restoreAllMocks());

describe("building grid", () => {
  it("labels every unit with its number, type and status for screen readers", () => {
    expect(unitSpokenLabel(held)).toBe("Unit 102, 2 BHK, On hold");
    expect(unitSpokenLabel(unit("5", { status: "on_hold", hold_expired: true }))).toBe("Unit 5, 2 BHK, On hold (expired)");
  });

  it("shows floors top first with a legend, and opens unit details", async () => {
    mockApi(makeUser("executive"), { get: { "/projects/1/inventory": inventory(units) } });
    renderApp("/projects/1");

    const grid = await screen.findByRole("grid", { name: "A Wing units by floor" });
    const rows = within(grid).getAllByRole("row");
    expect(within(rows[0]).getByRole("rowheader")).toHaveTextContent("Floor 2");
    expect(screen.getByRole("list", { name: "Unit status colours" })).toHaveTextContent("On hold 1");

    await userEvent.click(within(grid).getByRole("button", { name: "Unit 102, 2 BHK, On hold" }));
    const panel = await screen.findByRole("dialog", { name: "Unit 102" });
    expect(within(panel).getByText(/By Meera Shah/)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Anita Desai" })).toHaveAttribute("href", "/leads/9");
    // Executives look but can't hold or release
    expect(within(panel).queryByRole("button", { name: /hold/i })).not.toBeInTheDocument();
  });

  it("lets a manager hold an available unit", async () => {
    const { patch } = mockApi(makeUser("manager"), {
      get: { "/projects/1/inventory": inventory(units), "/leads/search": { items: [], total: 0, page: 1, page_size: 8 } },
      patch: { "/units/101/hold": () => unit("101", { status: "on_hold" }) },
    });
    vi.spyOn((await import("../lib/api")).api, "post").mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 8 } });
    renderApp("/projects/1");

    await userEvent.click(await screen.findByRole("button", { name: "Unit 101, 2 BHK, Available" }));
    const panel = await screen.findByRole("dialog", { name: "Unit 101" });
    await userEvent.click(within(panel).getByRole("button", { name: "Hold this unit" }));
    await userEvent.selectOptions(within(panel).getByLabelText("Hold for"), "24");
    await userEvent.click(within(panel).getByRole("button", { name: "Put on hold" }));

    await waitFor(() => expect(patch).toHaveBeenCalledWith("/units/101/hold", { hours: 24, lead_id: undefined, note: undefined }));
  });

  it("offers admin tools only to admins", async () => {
    mockApi(makeUser("admin"), { get: { "/projects/1/inventory": inventory(units), "/developers": [] } });
    renderApp("/projects/1");
    expect(await screen.findByRole("button", { name: "Add floors and units" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add building" })).toBeInTheDocument();
  });
});

describe("unit generator", () => {
  it("previews the numbering before creating", async () => {
    const empty = inventory([]);
    empty.buildings[0].floors = [];
    mockApi(makeUser("admin"), { get: { "/projects/1/inventory": empty } });
    renderApp("/projects/1");
    await userEvent.click(await screen.findByRole("button", { name: "Add floors and units" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Creates/)).toHaveTextContent("Creates 16 units: floor 1 101–104 up to floor 4 401–404");
    const to = within(dialog).getByLabelText("To floor");
    await userEvent.clear(to);
    await userEvent.type(to, "0");
    expect(within(dialog).getByRole("button", { name: "Create units" })).toBeDisabled();
  });
});
