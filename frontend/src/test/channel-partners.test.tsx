import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChannelPartner, PartnerCustomer } from "../hooks/useChannelPartners";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

const amit: ChannelPartner = { id: 3, name: "Amit Shah", company_name: "Square Realty", mobile: "+919820011111", email: "amit@square.in",
  rera_number: "A52100012345", notes: null, is_active: true, created_at: "2026-10-01T00:00:00Z", leads: 2, bookings: 1, booked_value: 4_200_000 };
const customers: PartnerCustomer[] = [
  { lead_id: 5, lead_code: "L-5", name: "Anita Desai", mobile: "+919876543210", status: "booked", project: "Habitat", owner: { id: 7, full_name: "Ravi Kumar", role: "executive" },
    created_at: "2026-10-20T05:00:00Z", booking_id: 9, booking_code: "BKG-00009", unit_no: "201", booked_project: "Habitat", agreed_price: 4_200_000, booking_date: "2026-10-27" },
  { lead_id: 6, lead_code: "L-6", name: "Rahul Patil", mobile: "+919123456780", status: "negotiation", project: null, owner: null,
    created_at: "2026-10-22T05:00:00Z", booking_id: null, booking_code: null, unit_no: null, booked_project: null, agreed_price: null, booking_date: null },
];

beforeEach(() => vi.restoreAllMocks());

describe("channel partners", () => {
  it("lists partners with company, contact and RERA number", async () => {
    mockApi(makeUser("manager"), { get: { "/channel-partners": [amit], "/inbox/count": { count: 0 } } });
    renderApp("/channel-partners");
    const row = (await screen.findAllByRole("row", { name: /Amit Shah/ }))[0];
    for (const t of ["Square Realty", "+91 98200 11111", "amit@square.in", "A52100012345"]) expect(row).toHaveTextContent(t);
  });

  it("adds a partner", async () => {
    const { post } = mockApi(makeUser("executive"), { get: { "/channel-partners": [], "/channel-partners/3": amit, "/channel-partners/3/customers": { items: [], total: 0 } }, post: { "/channel-partners": amit } });
    renderApp("/channel-partners");
    await userEvent.click(await screen.findByRole("button", { name: "Add partner" }));
    const d = await screen.findByRole("dialog", { name: "Add channel partner" });
    await userEvent.type(within(d).getByLabelText("Name"), "Amit Shah");
    await userEvent.type(within(d).getByLabelText("Company name"), "Square Realty");
    await userEvent.type(within(d).getByLabelText("Mobile number"), "9820011111");
    await userEvent.type(within(d).getByLabelText("RERA number (optional)"), "A52100012345");
    await userEvent.click(within(d).getByRole("button", { name: "Add partner" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/channel-partners", expect.objectContaining({ name: "Amit Shah", company_name: "Square Realty", mobile: "9820011111", rera_number: "A52100012345", email: null })));
    expect(await screen.findByRole("heading", { name: "Amit Shah" })).toBeInTheDocument();
  });

  it("partner page has Partner details and Customers sub-tabs", async () => {
    mockApi(makeUser("manager"), { get: { "/channel-partners/3": amit, "/channel-partners/3/customers": { items: customers, total: 2 } } });
    renderApp("/channel-partners/3");
    const details = await screen.findByRole("tabpanel", { name: "Partner details" });
    expect(details).toHaveTextContent("A52100012345");
    expect(details).toHaveTextContent("2 · 1 booked (₹42 L)");
    await userEvent.click(screen.getByRole("tab", { name: "Customers (2)" }));
    const table = await screen.findByRole("table", { name: "Customers brought by Amit Shah" });
    const anita = within(table).getByRole("row", { name: /Anita Desai/ });
    expect(anita).toHaveTextContent("BKG-00009");
    expect(anita).toHaveTextContent("Unit 201");
    expect(within(table).getByRole("row", { name: /Rahul Patil/ })).toHaveTextContent("Unassigned");
  });

  it("the lead form offers a partner only when the source is Channel partner", async () => {
    const { post } = mockApi(makeUser("executive"), { get: { "/projects": [], "/campaigns": [], "/channel-partners": [amit] },
      post: { "/leads/check-duplicates": { duplicates: [] }, "/leads": { lead: { id: 5 }, duplicates: [] } } });
    renderApp("/leads/new");
    await screen.findByLabelText("Source", { exact: true }, { timeout: 4000 });
    expect(screen.queryByLabelText("Channel partner")).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Source", { exact: true }), "channel_partner");
    const pick = await screen.findByLabelText("Channel partner");
    await userEvent.selectOptions(pick, "3");
    await userEvent.type(screen.getByLabelText("Full name"), "Anita Desai");
    await userEvent.type(screen.getByLabelText("Mobile", { exact: true }), "9876543210");
    await userEvent.click(screen.getByRole("button", { name: "Create lead" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/leads", expect.objectContaining({ source: "channel_partner", channel_partner_id: 3 })));
  });

  it("documents staff can't open it", async () => {
    mockApi(makeUser("docs"));
    renderApp("/channel-partners");
    expect(await screen.findByText("You don’t have access to this page")).toBeInTheDocument();
  });
});
