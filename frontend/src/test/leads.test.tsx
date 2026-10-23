import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Lead, LeadDetail } from "../lib/leads";
import { formatBudget, formatMobile, lakhToRupees, rupeesToLakh } from "../lib/leads";
import { httpError, makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

const exec = makeUser("executive", { id: 7, full_name: "Ravi Kumar" });

function lead(overrides: Partial<Lead> = {}): Lead {
  return {
    id: 11, lead_code: "LEAD-20261022-0001", name: "Anita Desai", mobile: "+919876543210",
    alt_mobile: null, email: null, city: "Pune", source: "99acres", sub_source: null,
    project: { id: 1, name: "Green Meadows" }, configuration: "2bhk", budget_min: 4_500_000,
    budget_max: 6_000_000, purpose: null, timeline: null, assigned_to: { id: 7, full_name: "Ravi Kumar", role: "executive" },
    status: "new", lost_reason: null, estimated_value: null, remarks: null, created_by: null,
    last_activity_at: "2026-10-22T10:00:00Z", created_at: "2026-10-22T10:00:00Z", updated_at: "2026-10-22T10:00:00Z",
    ...overrides,
  };
}

const detail = (overrides: Partial<LeadDetail> = {}): LeadDetail => ({
  ...lead(), can_edit: true,
  activities: [{ id: 1, type: "created", note: null, details: { source: "99acres" }, actor: { id: 7, full_name: "Ravi Kumar", role: "executive" }, created_at: "2026-10-22T10:00:00Z" }],
  ...overrides,
});

beforeEach(() => vi.restoreAllMocks());

describe("formatting", () => {
  it("shows Indian budgets in lakh and crore", () => {
    expect(formatBudget(4_500_000, 6_000_000)).toBe("₹45 L – ₹60 L");
    expect(formatBudget(null, 12_500_000)).toBe("Up to ₹1.25 Cr");
    expect(formatMobile("+919876543210")).toBe("+91 98765 43210");
    expect(lakhToRupees("45.5")).toBe(4_550_000);
    expect(rupeesToLakh(4_550_000)).toBe("45.5");
  });
});

describe("leads list", () => {
  it("shows leads with status, project and budget", async () => {
    mockApi(exec, { post: { "/leads/search": { items: [lead()], total: 1, page: 1, page_size: 25 } } });
    renderApp("/leads");

    const table = await screen.findByRole("table");
    expect(within(table).getByRole("link", { name: "Anita Desai" })).toBeInTheDocument();
    expect(within(table).getByText("New")).toBeInTheDocument();
    expect(within(table).getByText("₹45 L – ₹60 L")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: "Call Anita Desai" })).toHaveAttribute("href", "tel:+919876543210");
  });

  it("invites the user to add their first lead when there are none", async () => {
    mockApi(exec, { post: { "/leads/search": { items: [], total: 0, page: 1, page_size: 25 } } });
    renderApp("/leads");
    expect(await screen.findByText("No leads yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /add a lead/i })).toHaveAttribute("href", "/leads/new");
  });

  it("sends the search term in the request body, not the URL", async () => {
    const { post } = mockApi(exec, { post: { "/leads/search": { items: [], total: 0, page: 1, page_size: 25 } } });
    renderApp("/leads");
    await userEvent.type(await screen.findByRole("searchbox", { name: "Search leads" }), "98765");
    await waitFor(() => expect(post).toHaveBeenCalledWith("/leads/search", expect.objectContaining({ q: "98765" })));
  });

  it("hides New lead from docs staff", async () => {
    mockApi(makeUser("docs"), { post: { "/leads/search": { items: [], total: 0, page: 1, page_size: 25 } } });
    renderApp("/leads");
    expect(await screen.findByText("No leads yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /new lead/i })).not.toBeInTheDocument();
  });
});

describe("status change", () => {
  it("requires a reason before a lead can be marked lost", async () => {
    const { post } = mockApi(exec, {
      get: { "/leads/11": detail() },
      post: { "/leads/11/status": detail({ status: "lost", lost_reason: "Bought elsewhere" }) },
    });
    renderApp("/leads/11");

    await userEvent.click(await screen.findByRole("button", { name: /change status/i }));
    const dialog = screen.getByRole("dialog");
    await userEvent.selectOptions(within(dialog).getByLabelText("New status"), "lost");
    const submit = within(dialog).getByRole("button", { name: "Change status" });
    expect(submit).toBeDisabled();

    await userEvent.type(within(dialog).getByLabelText(/why was this lead lost/i), "Bought elsewhere");
    expect(submit).toBeEnabled();
    await userEvent.click(submit);

    expect(post).toHaveBeenCalledWith("/leads/11/status", { status: "lost", reason: "Bought elsewhere", note: undefined });
  });

  it("does not let executives choose Booked", async () => {
    mockApi(exec, { get: { "/leads/11": detail() } });
    renderApp("/leads/11");
    await userEvent.click(await screen.findByRole("button", { name: /change status/i }));
    expect(screen.getByRole("option", { name: /booked \(manager only\)/i })).toBeDisabled();
  });
});

describe("lead form", () => {
  it("warns about a possible duplicate when the mobile matches", async () => {
    mockApi(exec, {
      get: { "/projects": [] },
      post: {
        "/leads/duplicates": [{ id: 3, lead_code: "LEAD-20261020-0004", name: "Anita D", status: "contacted",
          assigned_to_name: "Meera Shah", matched_on: ["mobile"], can_view: false }],
      },
    });
    renderApp("/leads/new");

    await userEvent.type(await screen.findByLabelText("Mobile"), "98765 43210");
    await userEvent.tab();

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("This may be an existing lead");
    expect(banner).toHaveTextContent("LEAD-20261020-0004");
    expect(banner).toHaveTextContent("with Meera Shah");
  });

  it("shows the server's validation message", async () => {
    mockApi(exec, {
      get: { "/projects": [] },
      post: { "/leads": httpError(422, [{ loc: ["body", "mobile"], msg: "Value error, enter a valid 10-digit Indian mobile number" }]) },
    });
    renderApp("/leads/new");
    await userEvent.type(await screen.findByLabelText("Full name"), "Test");
    await userEvent.type(screen.getByLabelText("Mobile"), "12345");
    await userEvent.selectOptions(screen.getByLabelText("Source"), "walk_in");
    await userEvent.click(screen.getByRole("button", { name: "Create lead" }));
    expect(await screen.findByText("Mobile: enter a valid 10-digit Indian mobile number")).toBeInTheDocument();
  });
});
