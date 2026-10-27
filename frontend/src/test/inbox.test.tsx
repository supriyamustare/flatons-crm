import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InboxItem } from "../hooks/useInbox";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

const item = (id: number, name: string, extra: Partial<InboxItem> = {}): InboxItem => ({
  id, lead_code: `LEAD-${id}`, name, mobile: "+919876543210", source: "99acres", sub_source: "Green Meadows 2BHK",
  project: null, campaign: null, message: "Want a site visit on Sunday", created_at: new Date().toISOString(), ...extra,
});
const people = [{ id: 7, full_name: "Ravi Kumar", role: "executive" }, { id: 8, full_name: "Kiran Rao", role: "executive" }];

beforeEach(() => vi.restoreAllMocks());

describe("new enquiries inbox", () => {
  it("lists waiting enquiries and hands one to a person", async () => {
    let waiting = [item(1, "Anita Desai"), item(2, "Rahul Patil")];
    const { post } = mockApi(makeUser("manager"), {
      get: { "/inbox": () => ({ count: waiting.length, items: waiting }), "/inbox/count": () => ({ count: waiting.length }), "/users/assignable": people },
      post: { "/leads/1/assign": () => { waiting = waiting.filter((i) => i.id !== 1); return {}; } },
    });
    renderApp("/inbox");

    expect(await screen.findAllByText("Want a site visit on Sunday")).toHaveLength(2);
    expect(screen.getByText(/^2 waiting\./)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Assign Anita Desai to"), "7");
    await userEvent.click(screen.getAllByRole("button", { name: "Assign" })[0]);

    await waitFor(() => expect(post).toHaveBeenCalledWith("/leads/1/assign", { assigned_to_id: 7 }));
    await waitFor(() => expect(screen.queryByText("Anita Desai")).not.toBeInTheDocument());
    expect(screen.getByText("Rahul Patil")).toBeInTheDocument();
  });

  it("says all caught up when nothing is waiting", async () => {
    mockApi(makeUser("admin"), { get: { "/inbox": { count: 0, items: [] }, "/inbox/count": { count: 0 }, "/users/assignable": people } });
    renderApp("/inbox");
    expect(await screen.findByText("All caught up")).toBeInTheDocument();
  });

  it("shows the waiting count in the menu for managers", async () => {
    mockApi(makeUser("manager"), { get: { "/inbox/count": { count: 3 }, "/dashboard/admin": () => { throw new Error("not needed"); } } });
    renderApp("/");
    const [nav] = await screen.findAllByRole("navigation", { name: "Main" });
    const link = await within(nav).findByRole("link", { name: "Enquiries, 3 waiting" });
    expect(link).toHaveAttribute("href", "/inbox");
  });

  it("isn't available to executives", async () => {
    mockApi(makeUser("executive"));
    renderApp("/inbox");
    expect(await screen.findByText("You don’t have access to this page")).toBeInTheDocument();
  });
});

describe("connections (admin)", () => {
  it("shows the address and key once after creating, and can send a test", async () => {
    const conn = { id: 3, name: "99acres", kind: "99acres", is_active: true, default_campaign_id: null, default_project_id: null,
      received_count: 0, last_received_at: null, facebook_ready: false, path: "/api/inbound/3", created_at: "2026-10-27T00:00:00Z" };
    const { post } = mockApi(makeUser("admin"), {
      get: { "/integrations": [], "/campaigns": [], "/projects": [] },
      post: { "/integrations": { integration: conn, secret: "s3cret-key-abcdef" }, "/inbound/3?test=true": { status: "test", detail: "Test only. Would use: Test enquiry, +919876543210" } },
    });
    renderApp("/connections");
    await userEvent.click(await screen.findByRole("button", { name: "New connection" }));
    const form = await screen.findByRole("dialog", { name: "New connection" });
    await userEvent.selectOptions(within(form).getByLabelText("Where enquiries come from"), "99acres");
    await userEvent.click(within(form).getByRole("button", { name: "Create connection" }));

    const ready = await screen.findByRole("dialog", { name: "99acres is ready" });
    expect(within(ready).getByText("s3cret-key-abcdef")).toBeInTheDocument();
    expect(within(ready).getByText(/\/api\/inbound\/3\?key=s3cret-key-abcdef/)).toBeInTheDocument();
    expect(within(ready).getByText(/won’t be shown again/)).toBeInTheDocument();
    await userEvent.click(within(ready).getByRole("button", { name: "Send test enquiry" }));
    expect(await within(ready).findByText(/Would use: Test enquiry/)).toBeInTheDocument();
    expect(post).toHaveBeenCalledWith("/inbound/3?test=true", expect.objectContaining({ mobile: "9876543210" }), { headers: { "X-Flatons-Key": "s3cret-key-abcdef" } });
  });

  it("is for admins only", async () => {
    mockApi(makeUser("manager"), { get: { "/inbox/count": { count: 0 } } });
    renderApp("/connections");
    expect(await screen.findByText("You don’t have access to this page")).toBeInTheDocument();
  });
});
