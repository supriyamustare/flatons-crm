import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { mobileNavFor } from "../lib/nav";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const options = { projects: [{ id: 1, name: "Habitat" }, { id: 2, name: "Optimids" }], buildings: [{ id: 5, name: "Tower A", project_id: 1 }], owners: [{ id: 3, name: "Pooja Test" }], not_available: {} };
const dash = { as_of: "2026-11-23", headline: { active_accounts: 12, agreements_pending: 4, overdue_receivables: 450_000, open_tickets: 7 },
  money: { consideration: 38_000_000, outstanding: 21_000_000, collected: 4_200_000, awaiting_confirmation: 120_000, collection_efficiency_pct: 92.5 },
  exceptions: [{ key: "overdue", label: "Customers with overdue payments", count: 3, amount: 450_000, report: "finance#ageing" },
    { key: "sla", label: "Tickets past their SLA", count: 0, report: "operations#sla_breaches" }],
  upcoming: { "7": { count: 2, amount: 300_000 }, "15": { count: 3, amount: 420_000 }, "30": { count: 5, amount: 800_000 } }, ageing: { "1-30": 200_000, "31-60": 250_000, "61-90": 0, "90+": 0 } };
const fin = { as_of: "2026-11-23", period: {}, projects: [{ project: "Habitat", cases: 12, consideration: 38_000_000, demanded: 9_000_000, collected: 4_200_000, awaiting_confirmation: 0, due_total: 1, due_paid: 1, collection_efficiency_pct: 92.5 }],
  totals: {}, own_contribution: { required: 0, received: 0, items: [] }, upcoming: { "7": { count: 0, amount: 0, items: [] }, "15": { count: 0, amount: 0, items: [] }, "30": { count: 0, amount: 0, items: [] } },
  ageing: {}, ageing_items: [{ case_id: 4, case_code: "PSC-00004", customer: "Anita Desai", project: "Habitat", unit: "1114", owner: "Pooja", "1-30": 0, "31-60": 450_000, "61-90": 0, "90+": 0, overdue: 450_000 }],
  customers: [], disbursement_pending: [], unallocated: [], failed_payments: [], refunds_pending: [], adjustments: [], no_ledger: [],
  not_available: { tax_tds: "TDS isn't captured on receipts yet, so it can't be reconciled." } };

describe("MIS", () => {
  it("shows the headline and opens an exception's report", async () => {
    const { get } = mockApi(makeUser("management"), { get: { "/mis/options": options, "/mis/dashboard": dash, "/mis/reports/finance": fin } });
    renderApp("/mis");
    expect(await screen.findByText("Active customer accounts")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    const ex = screen.getByRole("region", { name: "Exceptions" });
    expect(within(ex).getByRole("button", { name: /Tickets past their SLA/ })).toBeDisabled();
    await userEvent.click(within(ex).getByRole("button", { name: /Customers with overdue payments/ }));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/mis/reports/finance", expect.anything()));
    const ageing = await screen.findByRole("region", { name: "Overdue receivables by age" });
    expect(within(ageing).getByRole("link", { name: "PSC-00004" })).toHaveAttribute("href", "/post-sales/4");
  });

  it("finance explains what isn't available; exports carry the filters", async () => {
    mockApi(makeUser("finance"), { get: { "/mis/options": options, "/mis/reports/finance": fin } });
    renderApp("/mis?tab=finance&project_id=1");
    expect(await screen.findByRole("region", { name: "Not available yet" })).toHaveTextContent("TDS isn't captured");
    const ageing = screen.getByRole("region", { name: "Overdue receivables by age" });
    expect(within(ageing).getByRole("link", { name: "CSV" })).toHaveAttribute("href", "/api/mis/export/finance/ageing?project_id=1");
  });

  it("filters go to the server", async () => {
    const { get } = mockApi(makeUser("crm_manager"), { get: { "/mis/options": options, "/mis/dashboard": dash } });
    renderApp("/mis");
    await screen.findByText("Active customer accounts");
    await userEvent.selectOptions(screen.getByLabelText("Project"), "2");
    await waitFor(() => expect(get).toHaveBeenCalledWith("/mis/dashboard", { params: { project_id: "2" } }));
  });

  it("the MIS menu is for management, finance, CRM managers and auditors", () => {
    const has = (r: Parameters<typeof mobileNavFor>[0]) => [...mobileNavFor(r).bar, ...mobileNavFor(r).more].some((i) => i.label === "MIS");
    expect(has("management")).toBe(true); expect(has("auditor")).toBe(true); expect(has("finance")).toBe(true);
    expect(has("postsales_exec")).toBe(false); expect(has("executive")).toBe(false);
  });
});
