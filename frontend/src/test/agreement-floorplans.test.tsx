import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgreementSection } from "../components/bookings/AgreementSection";
import { ProjectFloorPlans, UnitFloorPlans } from "../components/inventory/FloorPlans";
import type { FloorPlan } from "../hooks/useFloorPlans";
import type { Booking } from "../lib/bookings";
import { UNIT_STATUS_LABELS } from "../lib/inventory";
import { makeUser, mockApi } from "./mockApi";
import { renderWithProviders } from "./render";

beforeEach(() => vi.restoreAllMocks());

const booking = { id: 9, booking_code: "BKG-00009", status: "booked", booking_date: "2026-10-20", agreement_date: null,
  unit: { unit_no: "201" }, project: { name: "Habitat" } } as unknown as Booking;
const plans: FloorPlan[] = [
  { id: 1, project_id: 1, floor_id: 5, floor_number: 2, unit_type: null, title: "Floor 2 layout", file_name: "f2.png", file_type: "image/png", url: "/api/floor-plans/1/file", applies_to: "Floor 2" },
  { id: 2, project_id: 1, floor_id: null, floor_number: null, unit_type: null, title: "Site master plan", file_name: "m.pdf", file_type: "application/pdf", url: "/api/floor-plans/2/file", applies_to: "Whole project" },
];

describe("agreement done", () => {
  it("is what Sold is now called", () => {
    expect(UNIT_STATUS_LABELS.sold).toBe("Agreement done");
  });

  it("managers mark it with a date", async () => {
    const { post } = mockApi(makeUser("manager"), { post: { "/bookings/9/agreement": { ...booking, agreement_date: "2026-10-28" } } });
    renderWithProviders(<AgreementSection booking={booking} />);
    await userEvent.click(await screen.findByRole("button", { name: "Mark agreement done" }));
    const d = await screen.findByRole("dialog", { name: "Mark agreement done" });
    await userEvent.clear(within(d).getByLabelText("Agreement date"));
    await userEvent.type(within(d).getByLabelText("Agreement date"), "2026-10-28");
    await userEvent.click(within(d).getByRole("button", { name: "Mark agreement done" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/bookings/9/agreement", { agreement_date: "2026-10-28" }));
  });

  it("shows the date once done; executives can't change it", async () => {
    mockApi(makeUser("executive"));
    renderWithProviders(<AgreementSection booking={{ ...booking, agreement_date: "2026-10-28" }} />);
    expect(await screen.findByText(/on 28 October 2026/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });
});

describe("floor plans", () => {
  it("project page lists plans and managers can upload", async () => {
    const { post } = mockApi(makeUser("manager"), { get: { "/projects/1/floor-plans": plans }, post: { "/projects/1/floor-plans": plans[0] } });
    renderWithProviders(<ProjectFloorPlans projectId={1} floors={[{ id: 5, label: "Habitat: Floor 2" }]} />);
    expect(await screen.findByRole("link", { name: "Open Floor 2 layout" })).toHaveAttribute("href", "/api/floor-plans/1/file");
    expect(screen.getByText("Whole project")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Upload floor plan" }));
    const d = await screen.findByRole("dialog", { name: "Upload floor plan" });
    await userEvent.type(within(d).getByLabelText("Title"), "Typical floor");
    await userEvent.selectOptions(within(d).getByLabelText("Applies to"), "floor:5");
    await userEvent.upload(within(d).getByLabelText("File"), new File([new Uint8Array([0x89, 0x50])], "plan.png", { type: "image/png" }));
    await userEvent.click(within(d).getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, form] = post.mock.calls[0] as [string, FormData];
    expect(url).toBe("/projects/1/floor-plans");
    expect([form.get("title"), form.get("floor_id"), (form.get("file") as File).name]).toEqual(["Typical floor", "5", "plan.png"]);
  });

  it("executives can view but not upload or delete", async () => {
    mockApi(makeUser("executive"), { get: { "/projects/1/floor-plans": plans } });
    renderWithProviders(<ProjectFloorPlans projectId={1} floors={[]} />);
    await screen.findByRole("link", { name: "Open Floor 2 layout" });
    expect(screen.queryByRole("button", { name: "Upload floor plan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Delete/ })).not.toBeInTheDocument();
  });

  it("a unit shows its matching plans", async () => {
    mockApi(makeUser("executive"), { get: { "/units/11/floor-plans": [plans[0]] } });
    renderWithProviders(<UnitFloorPlans unitId={11} />);
    expect(await screen.findByRole("link", { name: /Floor 2 layout/ })).toHaveAttribute("href", "/api/floor-plans/1/file");
  });
});
