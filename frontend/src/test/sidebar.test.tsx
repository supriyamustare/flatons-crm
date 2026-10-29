import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

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
