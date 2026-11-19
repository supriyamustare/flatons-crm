import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Apt, CalItem, CaseApts } from "../hooks/useAppointments";
import type { CaseDetail } from "../hooks/usePostSales";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const istDay = (offset: number) => new Date(Date.now() + offset * 864e5).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
const at = (offset: number, hhmm: string) => new Date(`${istDay(offset)}T${hhmm}:00+05:30`).toISOString();
const kase = {
  id: 4, case_code: "PSC-00004", status: "accepted", onboarding_status: "approved", customer: "Anita Desai", project: "Habitat", unit_no: "1114",
  booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-11-17", agreed_price: 3_225_000, owner: null, sales_exec: null, created_at: "2026-11-17T05:00:00Z",
  kyc_done: 4, kyc_total: 4, returned_reason: null, clarification_reason: null, accepted_at: "2026-11-17T05:00:00Z", handover: [], profile: null, co_applicants: [],
  requirements: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: false, history: [],
} as unknown as CaseDetail;
const item = (over: Partial<CalItem>): CalItem => ({ id: "apt-1", source: "appointment", kind: "inspection", label: "Customer inspection", title: "Customer inspection", customer: "Anita Desai",
  case_code: "PSC-00004", starts_at: at(0, "11:00"), duration_min: 60, location: "Habitat site office", status: "scheduled", confirmed: false, owner: "Pooja Test",
  link: "/post-sales/4?tab=appointments", ...over });
const kinds = { inspection: "Customer inspection", possession: "Possession handover", registration: "Registration" };
const apt = (over: Partial<Apt>): Apt => ({ id: 1, apt_no: "APT-00001", kind: "inspection", label: "Customer inspection", title: null, starts_at: at(0, "11:00"), duration_min: 60,
  location: "Habitat site office", owner: { id: 2, full_name: "Pooja Test", role: "postsales_exec" }, required_docs: "ID proof", notes: null, status: "scheduled", status_reason: null,
  confirmed_on: null, confirmed_via: null, outcome: null, follow_up_on: null, rescheduled_from: null, can_act: true, ...over });
const apts = (items: Apt[]): CaseApts => ({ items, owners: [{ id: 2, full_name: "Pooja Test", role: "postsales_exec" }], can_schedule: true, kinds });

describe("calendar", () => {
  it("shows the week with each entry on its day, linking to the right place", async () => {
    const { get } = mockApi(makeUser("crm_manager"), { get: { "/calendar": [item({}), item({ id: "agr-1", source: "agreement", kind: "registration", label: "Registration",
      starts_at: at(0, "15:00"), location: "Haveli 1", confirmed: true, link: "/post-sales/4?tab=agreement", owner: null })] } });
    renderApp("/calendar");
    expect(await screen.findByRole("heading", { name: "Calendar" })).toBeInTheDocument();
    const week = await screen.findByRole("list", { name: "Week" });
    const todayCell = within(week).getAllByRole("listitem").find((li) => li.textContent?.includes("Today"))!;
    await within(todayCell).findByText(/Customer inspection/);
    expect(within(todayCell).getByRole("link", { name: /Customer inspection/ })).toHaveAttribute("href", "/post-sales/4?tab=appointments");
    expect(within(todayCell).getByRole("link", { name: /Registration/ })).toHaveAttribute("href", "/post-sales/4?tab=agreement");
    expect(todayCell).toHaveTextContent("Not confirmed");
    await userEvent.click(screen.getByLabelText("Only mine"));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/calendar", expect.objectContaining({ params: expect.objectContaining({ mine: true }) })));
  });

  it("is in the menu for post-sales staff and sales executives", async () => {
    mockApi(makeUser("executive"), { get: { "/calendar": [] } });
    renderApp("/calendar");
    expect((await screen.findAllByRole("link", { name: "Calendar" })).length).toBeGreaterThan(0);
  });
});

describe("appointments tab", () => {
  it("a double booking can be confirmed with 'Book anyway'", async () => {
    let calls = 0;
    const clash = Object.assign(new Error("clash"), { isAxiosError: true, response: { status: 409, data: { detail: "The owner already has customer inspection APT-00001 at 11:00 AM. Choose another time, or confirm the double booking." } } });
    const { post } = mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/appointments": apts([apt({})]) } });
    post.mockImplementation(async (_url: string, body?: unknown) => { calls++; if (!(body as { allow_clash?: boolean }).allow_clash) throw clash; return { data: apts([apt({}), apt({ id: 2, apt_no: "APT-00002", kind: "possession", label: "Possession handover" })]) }; });
    renderApp("/post-sales/4?tab=appointments");
    const panel = await screen.findByRole("tabpanel", { name: "Appointments" });
    await userEvent.click(within(panel).getByRole("button", { name: "Schedule" }));
    const d = await screen.findByRole("dialog", { name: "Schedule an appointment" });
    await userEvent.selectOptions(within(d).getByLabelText("Kind"), "possession");
    await userEvent.type(within(d).getByLabelText("When"), `${istDay(1)}T11:30`);
    await userEvent.click(within(d).getByRole("button", { name: "Schedule" }));
    expect(await within(d).findByText(/already has customer inspection/)).toBeInTheDocument();
    await userEvent.click(within(d).getByRole("button", { name: "Book anyway" }));
    await waitFor(() => expect(calls).toBe(2));
    expect((post.mock.calls[1][1] as { allow_clash: boolean }).allow_clash).toBe(true);
    expect(await screen.findByText("Possession handover scheduled")).toBeInTheDocument();
  });

  it("recording a no-show sets up the follow-up", async () => {
    const past = apt({ starts_at: at(-1, "11:00"), confirmed_on: "2026-11-18", confirmed_via: "call" });
    const { post } = mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/appointments": apts([past]) },
      post: { "/appointments/1/attendance": apts([{ ...past, status: "no_show", follow_up_on: istDay(1) }]) } });
    renderApp("/post-sales/4?tab=appointments");
    const panel = await screen.findByRole("tabpanel", { name: "Appointments" });
    await userEvent.click(within(panel).getByRole("button", { name: "Record attendance" }));
    const d = await screen.findByRole("dialog", { name: "Record attendance" });
    expect(within(d).getByRole("button", { name: "Save" })).toBeDisabled();  // attended needs an outcome
    await userEvent.click(within(d).getByLabelText("Didn’t come"));
    expect(d).toHaveTextContent("A follow-up will be set for tomorrow");
    await userEvent.click(within(d).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/appointments/1/attendance", { attended: false, outcome: null }));
    expect(await within(panel).findByText(/Follow up on .* and reschedule/)).toBeInTheDocument();
  });
});
