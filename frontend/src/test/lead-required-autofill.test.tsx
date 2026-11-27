import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

beforeEach(() => vi.restoreAllMocks());

const exec = makeUser("executive");
const match = (can_view: boolean) => [{ id: 5, lead_code: "LEAD-20261101-0005", name: "Anita Desai", status: "contacted", assigned_to_name: "Pooja", matched_on: ["mobile"], can_view }];
const detail = { id: 5, lead_code: "LEAD-20261101-0005", name: "Anita Desai", mobile: "9876543210", alt_mobile: null, email: "anita@example.com", city: "Pune", source: "99acres",
  sub_source: "Old listing", campaign: null, channel_partner: null, project: null, configuration: "2bhk", budget_min: 6_000_000, budget_max: 8_000_000, purpose: "self_use",
  timeline: "within_3_months", estimated_value: null, remarks: "Earlier enquiry", assigned_to: { id: 2, full_name: "Pooja", role: "executive" } };
const labelOf = (text: string) => screen.getByText(text, { selector: "label" });

describe("new lead: required fields and returning customers", () => {
  it("marks name, mobile, email and source with a star", async () => {
    mockApi(exec, { get: { "/projects": [] } });
    renderApp("/leads/new");
    await screen.findByLabelText("Full name");
    for (const l of ["Full name", "Mobile", "Email", "Source"]) expect(labelOf(l).className).toContain("after:content-['*']");
    expect(labelOf("City or locality").className).not.toContain("after:content-['*']");
    expect(screen.getByText("Required", { exact: false })).toBeInTheDocument();
  });

  it("Create lead stays disabled until all four required fields are filled", async () => {
    mockApi(exec, { get: { "/projects": [] } });
    renderApp("/leads/new");
    const create = () => screen.getByRole("button", { name: "Create lead" });
    await userEvent.type(await screen.findByLabelText("Full name"), "Anita");
    await userEvent.type(screen.getByLabelText("Mobile"), "98765 43210");
    await userEvent.selectOptions(screen.getByLabelText("Source"), "walk_in");
    expect(create()).toBeDisabled();  // no email yet
    await userEvent.type(screen.getByLabelText("Email"), "anita@example.com");
    expect(create()).toBeEnabled();
  });

  it("fills a returning customer's details, and Undo clears them", async () => {
    mockApi(exec, { get: { "/projects": [], "/leads/5": detail }, post: { "/leads/duplicates": match(true) } });
    renderApp("/leads/new");
    await userEvent.type(await screen.findByLabelText("Mobile"), "98765 43210");
    await userEvent.tab();
    await waitFor(() => expect(screen.getByLabelText("Email")).toHaveValue("anita@example.com"));
    expect(screen.getByLabelText("Full name")).toHaveValue("Anita Desai");
    expect(screen.getByLabelText("City or locality")).toHaveValue("Pune");
    expect(screen.getByLabelText("Source")).toHaveValue("99acres");
    expect(screen.getByLabelText("Remarks")).toHaveValue("");  // the old enquiry's remarks aren't copied
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent("LEAD-20261101-0005");
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByLabelText("Email")).toHaveValue("");
    expect(screen.getByLabelText("Mobile")).toHaveValue("98765 43210");  // what you typed stays
  });

  it("never fills from a lead you can't see", async () => {
    const { get } = mockApi(exec, { get: { "/projects": [], "/leads/5": detail }, post: { "/leads/duplicates": match(false) } });
    renderApp("/leads/new");
    await userEvent.type(await screen.findByLabelText("Mobile"), "98765 43210");
    await userEvent.tab();
    expect(await screen.findByRole("alert")).toHaveTextContent("This may be an existing lead");
    expect(screen.getByLabelText("Email")).toHaveValue("");
    expect(get).not.toHaveBeenCalledWith("/leads/5", expect.anything());
  });
});
