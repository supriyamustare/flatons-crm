import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe("left menu", () => {
  it("lists every page, and My account (with Sign out) is one block at the bottom", async () => {
    mockApi(makeUser("admin", { full_name: "Supriya Mustare" }), { get: { "/inbox/count": { count: 0 } } });
    renderApp("/account");
    const [nav] = await screen.findAllByRole("navigation", { name: "Main" });
    const labels = within(nav).getAllByRole("link").map((a) => a.textContent);
    for (const l of ["Dashboard", "Leads", "Enquiries", "Projects", "Connections", "Users"]) expect(labels).toContain(l);
    expect(labels).not.toContain("My account"); // not listed twice
    const [account] = screen.getAllByRole("region", { name: "My account" });
    expect(within(account).getByRole("link", { name: /Supriya Mustare\s*My account · Admin/ })).toHaveAttribute("href", "/account");
    expect(within(account).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("the menu list can scroll inside the panel on short screens", async () => {
    mockApi(makeUser("admin"), { get: { "/inbox/count": { count: 0 } } });
    renderApp("/account");
    const [nav] = await screen.findAllByRole("navigation", { name: "Main" });
    expect(nav.className).toMatch(/overflow-y-auto/);
    expect(nav.className).toMatch(/min-h-0/);
  });

  it("Sign out in the account block signs out", async () => {
    const { post } = mockApi(makeUser("manager"), { get: { "/inbox/count": { count: 0 } }, post: { "/auth/logout": {} } });
    renderApp("/account");
    const [account] = await screen.findAllByRole("region", { name: "My account" });
    await userEvent.click(within(account).getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/auth/logout"));
  });
});


describe("collapsible left menu", () => {
  it("collapses to icons and expands again; items keep their names and Sign out stays", async () => {
    mockApi(makeUser("admin", { full_name: "Supriya Mustare" }), { get: { "/inbox/count": { count: 3 } } });
    renderApp("/account");
    const toggle = await screen.findByRole("button", { name: "Collapse menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(toggle);

    const expand = screen.getByRole("button", { name: "Expand menu" });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    expect(localStorage.getItem("flatons.sidebar.collapsed")).toBe("1");
    const [nav] = screen.getAllByRole("navigation", { name: "Main" });
    const dash = within(nav).getByRole("link", { name: "Dashboard" }); // name still announced
    expect(dash).toHaveAttribute("title", "Dashboard"); // and shown on hover
    expect(within(nav).getByRole("link", { name: /^Enquiries/ })).toHaveTextContent("3");
    const [account] = screen.getAllByRole("region", { name: "My account" });
    expect(within(account).getByRole("link", { name: /Supriya Mustare, My account · Admin/ })).toHaveTextContent("SM");
    expect(within(account).getByRole("button", { name: "Sign out" })).toBeInTheDocument();

    await userEvent.click(expand);
    expect(screen.getByRole("button", { name: "Collapse menu" })).toHaveAttribute("aria-expanded", "true");
    expect(localStorage.getItem("flatons.sidebar.collapsed")).toBe("0");
    expect(within(nav).getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("title");
  });

  it("remembers the choice", async () => {
    localStorage.setItem("flatons.sidebar.collapsed", "1");
    mockApi(makeUser("manager"), { get: { "/inbox/count": { count: 0 } } });
    renderApp("/account");
    expect(await screen.findByRole("button", { name: "Expand menu" })).toBeInTheDocument();
  });
});
