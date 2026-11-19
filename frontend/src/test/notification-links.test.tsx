import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CaseDetail } from "../hooks/usePostSales";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const kase = {
  id: 4, case_code: "PSC-00004", status: "accepted", onboarding_status: "approved", customer: "Anita Desai", project: "Habitat", unit_no: "1114",
  booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-11-17", agreed_price: 3_225_000, owner: null, sales_exec: null, created_at: "2026-11-17T05:00:00Z",
  kyc_done: 4, kyc_total: 4, returned_reason: null, clarification_reason: null, accepted_at: "2026-11-17T05:00:00Z", handover: [], profile: null, co_applicants: [],
  requirements: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: false, history: [],
} as unknown as CaseDetail;
const ledger = { exists: false, can_edit: false, head_labels: {} };

describe("case tabs follow the address", () => {
  it("?tab=ledger opens the Ledger tab", async () => {
    mockApi(makeUser("finance_approver"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/ledger": ledger } });
    renderApp("/post-sales/4?tab=ledger");
    expect(await screen.findByRole("tab", { name: "Ledger" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("tabpanel", { name: "Ledger" })).toBeInTheDocument();
  });

  it("clicking a tab puts it in the address", async () => {
    mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/ledger": ledger } });
    renderApp("/post-sales/4");
    expect(await screen.findByRole("tab", { name: "Customer" })).toHaveAttribute("aria-selected", "true");  // accepted cases start on Customer
    await userEvent.click(screen.getByRole("tab", { name: "Ledger" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Ledger" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByRole("tab", { name: "Customer" })).toHaveAttribute("aria-selected", "false");
  });

  it("a tab the person can't see falls back to the usual one", async () => {
    mockApi(makeUser("legal"), { get: { "/post-sales/cases/4": kase } });
    renderApp("/post-sales/4?tab=ledger");
    expect(await screen.findByRole("tab", { name: "Customer" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("tab", { name: "Ledger" })).not.toBeInTheDocument();
  });
});

describe("notification bell", () => {
  it("opens the exact tab the notification is about", async () => {
    const note = { id: 1, type: "ledger_approval", title: "Ledger to approve: Anita Desai", body: "PSC-00004", link: "/post-sales/4?tab=ledger", read_at: null, created_at: "2026-11-19T05:00:00Z" };
    mockApi(makeUser("finance_approver"), { get: { "/notifications": { items: [note], unread: 1 }, "/post-sales/cases": { items: [], total: 0, counts: {} },
      "/post-sales/cases/4": kase, "/post-sales/cases/4/ledger": ledger }, post: { "/notifications/1/read": {} }, patch: { "/notifications/1/read": {} } });
    renderApp("/");
    await userEvent.click((await screen.findAllByRole("button", { name: /Notifications/ }))[0]);  // desktop menu and phone header each have a bell
    await userEvent.click(await screen.findByRole("button", { name: /Ledger to approve: Anita Desai/ }));
    expect(await screen.findByRole("tab", { name: "Ledger" })).toHaveAttribute("aria-selected", "true");
    expect(within(await screen.findByRole("tabpanel", { name: "Ledger" })).getByText(/No ledger yet/)).toBeInTheDocument();
  });
});
