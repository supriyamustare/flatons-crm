import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { PortalApp, papi } from "../portal/PortalApp";

beforeEach(() => { vi.restoreAllMocks(); });

const me = (units = 1) => ({ email: "anita@example.com", name: "Anita Desai",
  units: [{ case_id: 4, project: "Habitat", tower: "Habitat", unit: "1114", status: "Booked" }, { case_id: 9, project: "Optimids", tower: "A", unit: "302", status: "Booked" }].slice(0, units) });
const dash = { property: { project: "Habitat", tower: "Habitat", unit: "1114", status: "Booked" }, agreement: "Being prepared", next_appointment: null, pending_actions: ["Overdue payment: Rs 3,25,725 for Plinth"],
  payments: { headline: "Overdue payment", total_paid: 322_500, total_consideration: 3_608_171, outstanding: 3_285_671, pending_reconciliation: 0, next_milestone: "1st Slab",
    next_due: { stage: "Plinth", amount: 325_725, due_date: "2026-11-20", status: "Overdue payment" } } };
const pays = { headline: "Payment received - reconciliation pending", total_consideration: 3_608_171, total_paid: 0, pending_reconciliation: 322_500, outstanding: 3_608_171,
  stages: [{ stage: "Booking", amount: 325_725, paid: 0, due_date: "2026-11-26", status: "Payment received - reconciliation pending" }, { stage: "Plinth", amount: 325_725, paid: 0, due_date: null, status: "Not yet demanded" }],
  receipts: [{ receipt_no: "RCT-00001", date: "2026-11-26", amount: 322_500, mode: "neft", status: "Payment received - reconciliation pending" }] };

function routes(map: Record<string, unknown>) {
  return vi.spyOn(papi, "get").mockImplementation(async (url: string) => {
    const hit = Object.keys(map).find((k) => url === k);
    if (!hit) throw Object.assign(new Error("401"), { response: { status: 401, data: { detail: "Please sign in" } } });
    return { data: map[hit] } as never;
  });
}

describe("customer portal", () => {
  it("explains when the portal is switched off", async () => {
    routes({ "/status": { enabled: false, reason: "The customer portal needs HTTPS before it can be used." } });
    window.history.pushState({}, "", "/portal/sign-in");
    render(<PortalApp />);
    expect(await screen.findByText("The customer portal needs HTTPS before it can be used.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Your email address")).not.toBeInTheDocument();
  });

  it("signs in with an emailed code and shows My Property", async () => {
    let signedIn = false;
    vi.spyOn(papi, "get").mockImplementation(async (url: string) => {
      if (url === "/status") return { data: { enabled: true, reason: null } } as never;
      if (!signedIn) throw Object.assign(new Error("401"), { response: { status: 401 } });
      return { data: ({ "/me": me(), "/cases/4/dashboard": dash } as Record<string, unknown>)[url] } as never;
    });
    const post = vi.spyOn(papi, "post").mockImplementation(async (url: string) => {
      if (url === "/auth/verify") signedIn = true;
      return { data: url === "/auth/request" ? { message: "If this email belongs to a registered customer, we've sent a sign-in code to it." } : { ok: true } } as never;
    });
    window.history.pushState({}, "", "/portal/sign-in");
    render(<PortalApp />);
    await userEvent.type(await screen.findByLabelText("Your email address"), "anita@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Send me a code" }));
    await userEvent.type(await screen.findByLabelText("6-digit code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/auth/verify", { email: "anita@example.com", code: "123456" }));
    const prop = await screen.findByRole("region", { name: "My Property" });
    expect(prop).toHaveTextContent("Habitat · Habitat · Unit 1114"); expect(prop).toHaveTextContent("₹ 3,22,500"); expect(prop).toHaveTextContent("Plinth");
    expect(screen.getByRole("region", { name: "Needs your attention" })).toHaveTextContent("Overdue payment");
  });

  it("payments use plain language and explain overdue", async () => {
    routes({ "/me": me(), "/cases/4/payments": pays });
    window.history.pushState({}, "", "/portal/4/payments");
    render(<PortalApp />);
    const sched = await screen.findByRole("table", { name: "Payment schedule" });
    expect(within(sched).getByRole("row", { name: /Booking/ })).toHaveTextContent("Payment received — reconciliation pending");
    expect(within(sched).getByRole("row", { name: /Plinth/ })).toHaveTextContent("Not yet demanded");
    expect(screen.getByText(/shown as overdue only after its due date has passed/)).toBeInTheDocument();
  });

  it("customers with several units can switch between them", async () => {
    routes({ "/me": me(2), "/cases/4/dashboard": dash });
    window.history.pushState({}, "", "/portal/4");
    render(<PortalApp />);
    const sw = await screen.findByLabelText("Your unit");
    expect(within(sw).getAllByRole("option").map((o) => o.textContent)).toEqual(["Habitat · 1114", "Optimids · 302"]);
  });

  it("a /portal address opens the portal, not the staff sign-in", async () => {
    routes({ "/status": { enabled: true, reason: null } });
    window.history.pushState({}, "", "/portal/sign-in");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Customer portal" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send me a code" })).toBeInTheDocument();  // the portal sign-in, email first
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });
});
