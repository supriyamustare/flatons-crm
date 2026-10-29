import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatDuration } from "../lib/calls";
import { mobileNavFor } from "../lib/nav";
import type { Task } from "../lib/tasks";
import type { Visit } from "../lib/visits";
import { visitDayReached } from "../lib/visits";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

const exec = makeUser("executive", { id: 7, full_name: "Ravi Kumar" });
const leadRef = { id: 11, lead_code: "LEAD-20261023-0001", name: "Anita Desai", mobile: "+919876543210" };

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: 3, lead: leadRef, task_type: "call", due_at: new Date(Date.now() + 3_600_000).toISOString(),
    status: "pending", is_overdue: false, notes: null, completion_note: null, completed_at: null,
    rescheduled_from_id: null, reschedule_reason: null,
    assigned_to: { id: 7, full_name: "Ravi Kumar", role: "executive" }, created_by: null,
    created_at: "2026-10-23T05:00:00Z", ...overrides,
  };
}

function visit(overrides: Partial<Visit> = {}): Visit {
  return {
    id: 9, lead: leadRef, project: { id: 1, name: "Flatons Heights" },
    host: { id: 7, full_name: "Ravi Kumar", role: "executive" }, visit_source: "sales_follow_up",
    scheduled_at: new Date(Date.now() + 3 * 86_400_000).toISOString(), status: "scheduled",
    needs_update: false, notes: null, reschedule_count: 0, feedback: null, interest_level: null,
    next_action: null, closed_at: null, cancellation_reason: null, created_at: "2026-10-23T05:00:00Z",
    ...overrides,
  };
}

const visitPage = (items: Visit[], needs = 0) => ({
  items, total: items.length, page: 1, page_size: 50, counts: { upcoming: items.length, needs_update: needs },
});

beforeEach(() => vi.restoreAllMocks());

describe("helpers", () => {
  it("formats call durations", () => {
    expect(formatDuration(245)).toBe("4 min 5 s");
    expect(formatDuration(120)).toBe("2 min");
    expect(formatDuration(42)).toBe("42 s");
    expect(formatDuration(null)).toBe("");
  });

  it("knows when a visit's outcome can be recorded", () => {
    const now = new Date(2026, 9, 23, 9, 0);
    expect(visitDayReached(new Date(2026, 9, 23, 18, 0).toISOString(), now)).toBe(true);
    expect(visitDayReached(new Date(2026, 9, 24, 10, 0).toISOString(), now)).toBe(false);
  });

  it("puts the extra pages under More on phones", () => {
    const admin = mobileNavFor("admin");
    expect(admin.bar.map((i) => i.label)).toEqual(["Dashboard", "Leads", "Enquiries", "Follow-ups", "Site visits"]);
    expect(admin.more.map((i) => i.label)).toEqual(["Pipeline", "Bookings", "Channel partners", "Calls", "Reports", "Marketing", "Projects", "Connections", "Users", "My account"]);
    expect(mobileNavFor("docs").bar.map((i) => i.label)).toEqual(["Dashboard", "Leads"]);
  });
});

describe("logging a call from a follow-up", () => {
  it("needs an outcome, hides duration when not connected, and closes the follow-up", async () => {
    const { post } = mockApi(exec, {
      get: { "/tasks": { items: [task()], total: 1, page: 1, page_size: 50, counts: { today: 1, overdue: 0, upcoming: 0 } } },
      post: { "/calls": (b: unknown) => ({ ...(b as object), id: 1, lead: leadRef }) },
    });
    renderApp("/follow-ups");

    await userEvent.click(await screen.findByRole("link", { name: /call anita desai/i }));
    const dialog = await screen.findByRole("dialog", { name: "Log call with Anita Desai" });
    const save = within(dialog).getByRole("button", { name: "Save call" });
    expect(save).toBeDisabled();

    await userEvent.click(within(dialog).getByRole("button", { name: "No answer" }));
    expect(within(dialog).queryByLabelText(/duration/i)).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Interested" }));
    await userEvent.type(within(dialog).getByLabelText(/duration/i), "4");
    expect(within(dialog).getByRole("checkbox", { name: "Mark this follow-up as done" })).toBeChecked();
    await userEvent.click(save);

    await waitFor(() => expect(post).toHaveBeenCalledWith("/calls", expect.objectContaining({
      lead_id: 11, outcome: "interested", direction: "outgoing", duration_sec: 240, complete_task_id: 3,
    })));
  });
});

describe("site visits", () => {
  it("only allows rescheduling or cancelling before the visit day", async () => {
    mockApi(exec, { get: { "/visits": visitPage([visit()]) } });
    renderApp("/visits");

    await userEvent.click(await screen.findByRole("button", { name: "Update visit with Anita Desai" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "It happened" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "They didn’t come" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Change date" })).toHaveAttribute("aria-pressed", "true");
  });

  it("needs a reason to cancel", async () => {
    const { post } = mockApi(exec, {
      get: { "/visits": visitPage([visit()]) },
      post: { "/visits/9/cancel": () => visit({ status: "cancelled" }) },
    });
    renderApp("/visits");
    await userEvent.click(await screen.findByRole("button", { name: "Update visit with Anita Desai" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel visit" }));
    const submit = within(dialog).getAllByRole("button", { name: "Cancel visit" }).at(-1)!;
    expect(submit).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Why is it cancelled?"), "Bought elsewhere");
    await userEvent.click(submit);
    await waitFor(() => expect(post).toHaveBeenCalledWith("/visits/9/cancel", { reason: "Bought elsewhere" }));
  });

  it("flags visits whose time passed without an update", async () => {
    const past = visit({ scheduled_at: new Date(Date.now() - 5 * 3_600_000).toISOString(), needs_update: true });
    mockApi(exec, { get: { "/visits": visitPage([past], 1) } });
    renderApp("/visits");
    expect(await screen.findByText("1 visit has passed without an update.")).toBeInTheDocument();
    expect(screen.getByText(/Time has passed/)).toBeInTheDocument();
  });
});

describe("scheduling from the Site visits page", () => {
  it("asks for the lead, then the project and time", async () => {
    const lead = {
      id: 11, lead_code: "LEAD-1", name: "Anita Desai", mobile: "+919876543210", project: { id: 1, name: "Flatons Heights" },
      assigned_to: { id: 7, full_name: "Ravi Kumar", role: "executive" }, status: "new",
    };
    const { post } = mockApi(exec, {
      get: { "/visits": visitPage([]), "/projects": [{ id: 1, name: "Flatons Heights", is_active: true }] },
      post: {
        "/leads/search": { items: [lead], total: 1, page: 1, page_size: 6 },
        "/visits": (b: unknown) => ({ ...visit(), ...(b as object) }),
      },
    });
    renderApp("/visits");

    await userEvent.click((await screen.findAllByRole("button", { name: /schedule (a )?visit/i }))[0]);
    const dialog = await screen.findByRole("dialog", { name: "Schedule a site visit" });
    await userEvent.click(await within(dialog).findByRole("button", { name: /anita desai/i }));

    const form = await screen.findByRole("dialog", { name: "Site visit for Anita Desai" });
    expect(within(form).getByLabelText("Project")).toHaveValue("1"); // lead's project preselected
    await userEvent.click(within(form).getByRole("button", { name: "Tomorrow 10 am" }));
    await userEvent.click(within(form).getByRole("button", { name: "Schedule visit" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith("/visits", expect.objectContaining({ lead_id: 11, project_id: 1 })));
  });
});
