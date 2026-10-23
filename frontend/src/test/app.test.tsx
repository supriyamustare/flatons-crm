import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { httpError, makeUser, mockApi } from "./mockApi";
import { navFor } from "../lib/nav";
import type { Role, User } from "../lib/types";
import { renderApp } from "./render";

function signedInAs(user: User | null, extra: Record<string, unknown> = {}) {
  mockApi(user, { get: extra as Record<string, unknown> });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("navigation by role", () => {
  it("shows Users and Projects only to admins, Leads to everyone", () => {
    expect(navFor("admin").map((i) => i.label)).toEqual(expect.arrayContaining(["Users", "Projects", "Leads"]));
    for (const role of ["manager", "executive", "docs"] as Role[]) {
      const labels = navFor(role).map((i) => i.label);
      expect(labels).not.toContain("Users");
      expect(labels).not.toContain("Projects");
      expect(labels).toContain("Leads");
    }
  });

  it("executive's sidebar has no Users link", async () => {
    signedInAs(makeUser("executive"));
    renderApp("/");
    const navs = await screen.findAllByRole("navigation", { name: "Main" });
    for (const nav of navs) {
      expect(within(nav).queryByRole("link", { name: /users/i })).not.toBeInTheDocument();
      expect(within(nav).getByRole("link", { name: /dashboard/i })).toBeInTheDocument();
    }
  });

  it("admin's sidebar includes Users", async () => {
    signedInAs(makeUser("admin"), { "/users": [] });
    renderApp("/");
    const [nav] = await screen.findAllByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: /users/i })).toBeInTheDocument();
  });
});

describe("route protection", () => {
  it("sends signed-out visitors to the sign-in page", async () => {
    signedInAs(null);
    vi.spyOn(api, "post").mockRejectedValue(httpError(401, "Not authenticated"));
    renderApp("/users");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows a no-access page when an executive opens /users directly", async () => {
    signedInAs(makeUser("executive"));
    renderApp("/users");
    expect(await screen.findByText("You don’t have access to this page")).toBeInTheDocument();
  });
});

describe("sign in", () => {
  it("shows the server's message when the password is wrong", async () => {
    signedInAs(null);
    vi.spyOn(api, "post").mockRejectedValue(httpError(401, "Incorrect email or password"));
    renderApp("/login");

    await userEvent.type(await screen.findByLabelText("Email"), "ravi@flatons.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password");
  });

  it("goes to the dashboard after a successful sign in", async () => {
    signedInAs(null);
    vi.spyOn(api, "post").mockResolvedValue({ data: makeUser("executive", { full_name: "Ravi Kumar" }) });
    renderApp("/login");

    await userEvent.type(await screen.findByLabelText("Email"), "ravi@flatons.com");
    await userEvent.type(screen.getByLabelText("Password"), "right-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: /, Ravi$/ })).toBeInTheDocument();
  });
});

describe("users page", () => {
  it("lists users with their roles", async () => {
    const admin = makeUser("admin", { full_name: "Supriya Mustare" });
    signedInAs(admin, {
      "/users": [admin, makeUser("executive", { id: 2, full_name: "Ravi Kumar", is_active: false })],
    });
    renderApp("/users");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Ravi Kumar")).toBeInTheDocument();
    expect(within(table).getByText("Sales executive")).toBeInTheDocument();
    expect(within(table).getByText("Deactivated")).toBeInTheDocument();
  });

  it("offers a retry when the list fails to load", async () => {
    signedInAs(makeUser("admin"), { "/users": httpError(500, "Server error") });
    renderApp("/users");

    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("shows validation errors from the server when adding a user", async () => {
    signedInAs(makeUser("admin"), { "/users": [makeUser("admin")] });
    vi.spyOn(api, "post").mockRejectedValue(
      httpError(409, "A user with this email already exists"),
    );
    renderApp("/users");

    await userEvent.click(await screen.findByRole("button", { name: /add user/i }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Full name"), "Ravi Kumar");
    await userEvent.type(within(dialog).getByLabelText("Email"), "ravi@flatons.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add user" }));

    await waitFor(() =>
      expect(within(dialog).getByRole("alert")).toHaveTextContent("A user with this email already exists"),
    );
  });
});
