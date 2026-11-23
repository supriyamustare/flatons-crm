import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CaseDetail } from "../hooks/usePostSales";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const events = { payment_received: { label: "Payment received (receipt issued)", fields: ["customer", "project", "unit", "case_code", "company", "amount", "receipt_no", "received_on"], channels: ["email"] } };
const tpl = (over: Record<string, unknown>) => ({ id: 7, event: "payment_received", channel: "email", project_id: null, version: 1, language: "English", subject: "Payment received: {receipt_no}",
  body: "Dear {customer}, we received Rs {amount}.", mandatory: false, delay_minutes: 0, status: "draft", author: "Starting draft", approved_by: null, approved_at: null,
  created_at: "2026-11-23T05:00:00Z", can_edit: true, can_approve: true, ...over });
const list = (templates: unknown[]) => ({ events, templates, channels: { email: "Email isn't set up yet (SMTP settings on the server)", sms: "SMS provider isn't chosen yet", whatsapp: "WhatsApp provider isn't chosen yet" }, projects: [{ id: 1, name: "Habitat" }] });

describe("communications", () => {
  it("explains held channels; someone else approves a draft", async () => {
    const { post } = mockApi(makeUser("crm_manager"), { get: { "/comms/templates": list([tpl({})]) }, post: { "/comms/templates/7/approve": list([tpl({ status: "approved", can_approve: false, can_edit: false })]) } });
    renderApp("/communications");
    expect(await screen.findByText(/Email: Email isn't set up yet/)).toBeInTheDocument();
    const item = screen.getByRole("listitem", { name: "Payment received (receipt issued)" });
    await userEvent.click(within(item).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/comms/templates/7/approve"));
    expect(await within(item).findByText("In use")).toBeInTheDocument();
  });

  it("the author can't approve their own draft", async () => {
    mockApi(makeUser("crm_manager"), { get: { "/comms/templates": list([tpl({ author: "Meera", can_approve: false })]) } });
    renderApp("/communications");
    expect(await screen.findByText("Someone other than the author approves")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("a new version lists the fields and saves a draft", async () => {
    const { post } = mockApi(makeUser("crm_manager"), { get: { "/comms/templates": list([tpl({ status: "approved", can_approve: false, can_edit: false })]) }, post: { "/comms/templates": list([]) } });
    renderApp("/communications");
    await userEvent.click(await screen.findByRole("button", { name: "New email version" }));
    const d = await screen.findByRole("dialog", { name: "New version" });
    expect(d).toHaveTextContent("{receipt_no}"); expect(d).toHaveTextContent("No links");
    await userEvent.clear(within(d).getByLabelText("Message")); await userEvent.type(within(d).getByLabelText("Message"), "Dear {{customer}, thank you for Rs {{amount}.");
    await userEvent.click(within(d).getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/comms/templates", expect.objectContaining({ event: "payment_received", channel: "email", body: "Dear {customer}, thank you for Rs {amount}." })));
  });

  it("the outbox offers retry for held messages", async () => {
    mockApi(makeUser("admin"), { get: { "/comms/templates": list([]), "/comms/messages": [{ id: 3, case_id: 4, event: "payment_received", event_label: "Payment received", channel: "email",
      recipient: "anita@example.com", subject: "Payment received: RCT-00001", body: "x", status: "held", reason: "Email isn't set up yet", attempts: 0, send_after: "2026-11-23T05:00:00Z",
      sent_at: null, created_at: "2026-11-23T05:00:00Z", template_version: 1 }] } });
    renderApp("/communications?tab=outbox");
    const row = await screen.findByRole("row", { name: /anita@example.com/ });
    expect(row).toHaveTextContent("Held"); expect(within(row).getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("the case tab shows consent, channels and history", async () => {
    const kase = { id: 4, case_code: "PSC-00004", status: "accepted", onboarding_status: "approved", customer: "Anita Desai", project: "Habitat", unit_no: "1114",
      booking_id: 9, booking_code: "BKG-00009", booking_date: "2026-11-17", agreed_price: 3_225_000, owner: null, sales_exec: null, created_at: "2026-11-17T05:00:00Z",
      kyc_done: 4, kyc_total: 4, returned_reason: null, clarification_reason: null, accepted_at: "2026-11-17T05:00:00Z", handover: [], profile: null, co_applicants: [],
      requirements: [], documents: [], profile_problems: [], can_edit: false, can_view_kyc: false, history: [] } as unknown as CaseDetail;
    mockApi(makeUser("postsales_exec"), { get: { "/post-sales/cases/4": kase, "/post-sales/cases/4/communications": { channels: { email: null, sms: "SMS provider isn't chosen yet", whatsapp: null },
      preferences: { email: "anita@example.com", mobile: "9000000001", contact_email: true, contact_sms: false, contact_whatsapp: false, consent_electronic_at: "2026-11-18T05:00:00Z", preferred_language: null },
      messages: [{ id: 1, event: "payment_received", event_label: "Payment received (receipt issued)", channel: "email", recipient: "anita@example.com", subject: "Payment received: RCT-00001",
        body: "Dear Anita", status: "sent", reason: null, attempts: 1, sent_at: "2026-11-23T05:02:00Z", created_at: "2026-11-23T05:00:00Z", template_version: 2 }] } } });
    renderApp("/post-sales/4?tab=communications");
    const panel = await screen.findByRole("tabpanel", { name: "Communications" });
    expect(within(panel).getByRole("region", { name: "Preferences" })).toHaveTextContent("SMS 9000000001: opted out");
    expect(within(panel).getByRole("region", { name: "Message history" })).toHaveTextContent("Payment received (receipt issued)");
    expect(panel).toHaveTextContent("SMS: SMS provider isn't chosen yet");
  });
});
