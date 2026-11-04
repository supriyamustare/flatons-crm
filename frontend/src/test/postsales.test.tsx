import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CaseDetail } from "../hooks/usePostSales";
import { mobileNavFor, navFor } from "../lib/nav";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const base: CaseDetail = {
  id: 4, case_code: "PSC-00004", status: "handover_pending", onboarding_status: "not_started", customer: "Anita Desai", project: "Habitat",
  unit_no: "201", booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-10-27", agreed_price: 4_000_000, owner: null,
  sales_exec: { id: 7, full_name: "Ravi Kumar", role: "executive" }, created_at: "2026-10-27T05:00:00Z", kyc_done: 0, kyc_total: 4,
  returned_reason: null, clarification_reason: null, accepted_at: null,
  handover: [{ item: "Customer name", ok: true, required: true }, { item: "Email", ok: false, required: false }],
  profile: null, co_applicants: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: true, history: [],
  requirements: [{ applicant_id: null, applicant: "Anita Desai", key: "pan", label: "PAN card", accepted_types: ["pan"], status: "missing", document_id: null }],
};

describe("post-sales access", () => {
  it("post-sales roles get Post-sales and no Leads; sales keep Leads", () => {
    expect(navFor("postsales_exec").map((i) => i.label)).toEqual(expect.arrayContaining(["Post-sales", "Bookings", "Projects"]));
    expect(navFor("finance").map((i) => i.label)).not.toContain("Leads");
    expect(navFor("executive").map((i) => i.label)).not.toContain("Post-sales");
    expect(mobileNavFor("postsales_exec").bar.map((i) => i.label)).toContain("Post-sales");
  });

  it("post-sales staff land on a post-sales home, not the sales dashboard", async () => {
    const { get } = mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases": { items: [], total: 2, counts: { "status:handover_pending": 3 } } } });
    renderApp("/");
    const glance = await screen.findByRole("region", { name: "Post-sales at a glance" });
    await waitFor(() => expect(glance).toHaveTextContent("Handover pending3"));
    expect(get.mock.calls.map((c) => c[0])).not.toContain("/dashboard/overview");
  });

  it("executives can't open post-sales", async () => {
    mockApi(makeUser("executive"));
    renderApp("/post-sales");
    expect(await screen.findByText("You don’t have access to this page")).toBeInTheDocument();
  });
});

describe("case page", () => {
  it("accepts a handover", async () => {
    const { post } = mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": base },
      post: { "/post-sales/cases/4/accept": { ...base, status: "accepted", onboarding_status: "documents_pending", can_edit: true } } });
    renderApp("/post-sales/4");
    const panel = await screen.findByRole("tabpanel", { name: "Handover" });
    expect(within(panel).getByText("Email")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Accept handover" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/accept", undefined));
  });

  it("returning to sales needs a reason", async () => {
    const { post } = mockApi(makeUser("crm_manager"), { get: { "/post-sales/cases/4": base },
      post: { "/post-sales/cases/4/return": { ...base, status: "returned_to_sales", returned_reason: "Email missing" } } });
    renderApp("/post-sales/4");
    await userEvent.click(await screen.findByRole("button", { name: "Return to sales" }));
    const d = await screen.findByRole("dialog", { name: "Return to sales" });
    expect(within(d).getByRole("button", { name: "Return to sales" })).toBeDisabled();
    await userEvent.type(within(d).getByLabelText("What does sales need to fix?"), "Email missing");
    await userEvent.click(within(d).getByRole("button", { name: "Return to sales" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/post-sales/cases/4/return", { reason: "Email missing" }));
  });

  it("KYC tab: the uploader can't verify their own document", async () => {
    const doc = { id: 11, co_applicant_id: null, doc_type: "pan" as const, status: "pending", file_name: "pan.png", file_type: "image/png", expiry_date: null,
      review_note: null, uploaded_at: "2026-10-28T05:00:00Z", uploaded_by_id: 1, reviewed_at: null, superseded_by_id: null };
    const c = { ...base, status: "accepted" as const, onboarding_status: "under_review" as const, can_edit: true, documents: [doc],
      requirements: [{ ...base.requirements[0], status: "pending" as const, document_id: 11 }] };
    mockApi(makeUser("postsales_exec", { id: 1 }), { get: { "/post-sales/cases/4": c } });
    renderApp("/post-sales/4");
    await userEvent.click(await screen.findByRole("tab", { name: "KYC" }));
    const panel = screen.getByRole("tabpanel", { name: "KYC" });
    expect(within(panel).getByText("Another person must review")).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Verify" })).not.toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: /View/ })).toHaveAttribute("href", "/api/post-sales/kyc/11/file");
  });
});

describe("users page", () => {
  it("offers the post-sales roles", async () => {
    const { ROLE_LABELS } = await import("../lib/types");
    expect(Object.keys(ROLE_LABELS)).toHaveLength(15);
    expect(ROLE_LABELS.finance_approver).toBe("Finance approver");
  });
});

describe("legal & bank details", () => {
  it("saves only the editable legal fields", async () => {
    const { LegalBankDialog } = await import("../components/inventory/LegalBankDialog");
    const { renderWithProviders } = await import("./render");
    const legal = { developer_legal_name: "Avnee Estates LLP", rera_number: null, registered_address: null, signatory_name: null,
      signatory_designation: null, gstin: null, cin: null, updated_at: "2026-10-28T05:00:00Z" };
    const { put } = mockApi(makeUser("admin"), { get: { "/projects/1/legal": legal, "/projects/1/bank": { bank_name: null, account_holder_name: null,
      account_number_masked: null, account_number: null, ifsc: null, branch: null, updated_at: null } }, put: { "/projects/1/legal": legal } });
    renderWithProviders(<LegalBankDialog projectId={1} onClose={() => {}} />);
    await userEvent.type(await screen.findByLabelText("GSTIN"), "27AABFA1234C1Z9");
    await userEvent.click(screen.getByRole("button", { name: "Save legal details" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    const body = put.mock.calls[0][1] as Record<string, unknown>;
    expect(body).not.toHaveProperty("updated_at");
    expect(body.gstin).toBe("27AABFA1234C1Z9");
  });
});

describe("leads pages", () => {
  it("post-sales staff get the no-access page, not a broken Leads page", async () => {
    mockApi(makeUser("finance"));
    renderApp("/leads");
    expect(await screen.findByText("You don’t have access to this page")).toBeInTheDocument();
  });
});

describe("header", () => {
  it("post-sales staff don't get the lead search or Add lead", async () => {
    mockApi(makeUser("crm_manager"), { get: { "/post-sales/cases": { items: [], total: 0, counts: {} } } });
    renderApp("/");
    await screen.findByRole("region", { name: "Post-sales at a glance" });
    expect(screen.queryByRole("button", { name: /Add lead/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Add lead/ })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Search leads/)).not.toBeInTheDocument();
  });
});

describe("error messages", () => {
  it("show the server's plain message once, without the technical prefix", async () => {
    const { errorMessage } = await import("../lib/api");
    const { AxiosError } = await import("axios");
    const err = new AxiosError("422", "ERR", undefined, undefined, {
      status: 422, statusText: "", headers: {}, config: {} as never,
      data: { detail: [{ loc: ["body", "gstin"], msg: "Value error, GSTIN must be 15 characters (this one has 11)" }] },
    });
    expect(errorMessage(err)).toBe("GSTIN must be 15 characters (this one has 11)");
  });
});
