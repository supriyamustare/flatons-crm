import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { duePresets, formatDue, localInputToIso, toLocalInput } from "../lib/tasks";
import type { Task, TaskPage } from "../lib/tasks";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

const exec = makeUser("executive", { id: 7, full_name: "Ravi Kumar" });

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: 1, lead: { id: 11, lead_code: "LEAD-20261023-0001", name: "Anita Desai", mobile: "+919876543210" },
    task_type: "call", due_at: new Date(Date.now() + 3_600_000).toISOString(), status: "pending",
    is_overdue: false, notes: "Share price sheet", completion_note: null, completed_at: null,
    rescheduled_from_id: null, reschedule_reason: null,
    assigned_to: { id: 7, full_name: "Ravi Kumar", role: "executive" }, created_by: null,
    created_at: "2026-10-23T05:00:00Z", ...overrides,
  };
}

function page(items: Task[], counts = { today: items.length, overdue: 0, upcoming: 0 }): TaskPage {
  return { items, total: items.length, page: 1, page_size: 50, counts };
}

beforeEach(() => vi.restoreAllMocks());

describe("date helpers", () => {
  it("describes due times relative to today", () => {
    const now = new Date(2026, 9, 23, 9, 0);
    expect(formatDue(new Date(2026, 9, 23, 15, 0).toISOString(), now)).toMatch(/^Today, 3:00/);
    expect(formatDue(new Date(2026, 9, 24, 10, 0).toISOString(), now)).toMatch(/^Tomorrow, 10:00/);
    expect(formatDue(new Date(2026, 9, 22, 17, 0).toISOString(), now)).toMatch(/^Yesterday/);
  });

  it("sends due times with a timezone, as the API requires", () => {
    const iso = localInputToIso(toLocalInput(new Date(2026, 9, 24, 10, 0)));
    expect(iso).toMatch(/Z$/);
    expect(new Date(iso).getTime()).toBe(new Date(2026, 9, 24, 10, 0).getTime());
  });

  it("offers presets that are all in the future", () => {
    const now = new Date();
    for (const p of duePresets(now)) expect(p.value.getTime()).toBeGreaterThan(now.getTime());
  });
});

describe("follow-ups page", () => {
  it("shows counts on the tabs and highlights overdue follow-ups", async () => {
    const late = task({ id: 2, is_overdue: true, due_at: new Date(Date.now() - 3_600_000).toISOString() });
    mockApi(exec, { get: { "/tasks": page([late, task()], { today: 2, overdue: 1, upcoming: 4 }) } });
    renderApp("/follow-ups");

    const tabs = await screen.findByRole("tablist", { name: "Follow-up views" });
    await waitFor(() => expect(within(tabs).getByRole("tab", { name: "Overdue, 1" })).toBeInTheDocument());
    expect(within(tabs).getByRole("tab", { name: "Upcoming, 4" })).toBeInTheDocument();
    expect(screen.getByText(/^Overdue ·/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /call anita desai/i })[0]).toHaveAttribute("href", "tel:+919876543210");
  });

  it("asks what happened before marking a follow-up done", async () => {
    const { post } = mockApi(exec, {
      get: { "/tasks": page([task()]) },
      post: { "/tasks/1/complete": (b: unknown) => ({ ...task(), status: "completed", ...(b as object) }) },
    });
    renderApp("/follow-ups");

    await userEvent.click(await screen.findByRole("button", { name: "Mark Call with Anita Desai as done" }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Mark done" });
    expect(submit).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("What happened?"), "Visiting Sunday");
    await userEvent.click(submit);

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/tasks/1/complete", { completion_note: "Visiting Sunday" }),
    );
  });

  it("shows a friendly message when nothing is due", async () => {
    mockApi(exec, { get: { "/tasks": page([]) } });
    renderApp("/follow-ups");
    expect(await screen.findByText("Nothing due today.")).toBeInTheDocument();
  });

  it("is not available to documents staff", async () => {
    mockApi(makeUser("docs"));
    renderApp("/follow-ups");
    expect(await screen.findByText("You don’t have access to this page")).toBeInTheDocument();
  });
});

describe("notification bell", () => {
  it("shows the unread count and opens the linked page", async () => {
    const { patch } = mockApi(exec, {
      get: {
        "/notifications": {
          unread_count: 1,
          items: [{ id: 5, type: "lead_assigned", title: "Lead assigned: Anita Desai", body: "Meera Shah assigned LEAD-1 to you",
            link: "/follow-ups", read_at: null, created_at: "2026-10-23T05:00:00Z" }],
        },
        "/tasks": page([]),
      },
      patch: { "/notifications/5/read": { read_at: "2026-10-23T06:00:00Z" } },
    });
    renderApp("/");

    const [bell] = await screen.findAllByRole("button", { name: "Notifications, 1 unread" });
    await userEvent.click(bell);
    await userEvent.click(await screen.findByRole("button", { name: /lead assigned: anita desai/i }));

    expect(patch).toHaveBeenCalledWith("/notifications/5/read");
    expect(await screen.findByRole("heading", { name: "Follow-ups" })).toBeInTheDocument();
  });
});
