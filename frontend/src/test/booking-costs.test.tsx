import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BookingCosts, UploadUnitFile } from "../components/inventory/UnitSections";
import { makeUser, mockApi } from "./mockApi";
import { renderWithProviders } from "./render";

beforeEach(() => vi.restoreAllMocks());

const unit = { id: 7, unit_no: "1114", status: "available" } as never;
const sheet = (over: Record<string, unknown> = {}) => ({ ready: true, cost: 3_525_000, base_cost: 3_225_000, parking_no: "P-12", parking_charges: 300_000, gst: 35_250, stamp_duty: 246_800,
  registration: 30_000, legal_charges: 10_000, furnishing: 0, other_charges: 0, other_charges_label: "Other charges", grand_total: 3_847_050, overrides: { legal_charges: 10_000, parking_no: "P-12", parking_charges: 300_000 }, ...over });
const files = [{ id: 3, title: "Signed cost sheet", file_name: "cs.pdf", uploaded_by: "Ravi", uploaded_at: "2026-11-27T05:00:00Z", url: "/api/units/files/3" }];

describe("parking and booking costs on a flat", () => {
  it("parking on top, then the costs in order, and no files block", async () => {
    mockApi(makeUser("executive"), { get: { "/units/7/cost-sheet": sheet(), "/units/7/files": files } });
    renderWithProviders(<BookingCosts unit={unit} />);
    const sec = await screen.findByRole("region", { name: "Parking and booking costs" });
    await within(sec).findByText("P-12");
    expect(sec).toHaveTextContent("Parking price₹ 3,00,000");
    const costs = within(sec).getByLabelText("Booking costs");
    const labels = within(costs).getAllByRole("term").map((t) => t.textContent);
    expect(labels).toEqual(["Agreement cost", "Registration", "Stamp duty", "GST", "Legal charges", "Furnishing", "Total payable"]);
    expect(costs).toHaveTextContent("Stamp duty₹ 2,46,800"); expect(costs).toHaveTextContent("Total payable₹ 38,47,050");
    expect(sec).not.toHaveTextContent("Files for this flat"); expect(sec).not.toHaveTextContent("No files yet");
    expect(within(sec).queryByRole("button", { name: /Edit parking/ })).not.toBeInTheDocument();
  });

  it("saving parking keeps the flat's other numbers", async () => {
    const { put } = mockApi(makeUser("manager"), { get: { "/units/7/cost-sheet": sheet(), "/units/7/files": [] }, put: { "/units/7/cost-sheet": sheet({ parking_no: "P-14" }) } });
    renderWithProviders(<BookingCosts unit={unit} />);
    await userEvent.click(await screen.findByRole("button", { name: /Edit parking/ }));
    const no = screen.getByLabelText("Parking no."); await userEvent.clear(no); await userEvent.type(no, "P-14");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/units/7/cost-sheet", { legal_charges: 10_000, parking_no: "P-14", parking_charges: 300_000 }));
  });

  it("Upload file at the bottom attaches a file straight away and lists it under the button", async () => {
    let list: unknown[] = [];
    const { post } = mockApi(makeUser("manager"), { get: { "/units/7/files": [] } });
    post.mockImplementation(async () => { list = files; return { data: files } as never; });
    renderWithProviders(<UploadUnitFile unit={unit} />);
    expect(screen.queryByRole("list", { name: "Files for this flat" })).not.toBeInTheDocument();  // nothing shown when there are no files
    await userEvent.upload(await screen.findByLabelText("Upload file"), new File(["%PDF"], "cs.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(((post.mock.calls[0][1] as FormData).get("file") as File).name).toBe("cs.pdf");
    expect(await screen.findByRole("link", { name: "Signed cost sheet" })).toHaveAttribute("href", "/api/units/files/3");
    void list;
  });

  it("executives see a flat's files but no upload button; with no files, nothing", async () => {
    mockApi(makeUser("executive"), { get: { "/units/7/files": files } });
    const { unmount } = renderWithProviders(<UploadUnitFile unit={unit} />);
    expect(await screen.findByRole("link", { name: "Signed cost sheet" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Upload file")).not.toBeInTheDocument();
    unmount(); vi.restoreAllMocks();
    mockApi(makeUser("executive"), { get: { "/units/7/files": [] } });
    renderWithProviders(<UploadUnitFile unit={unit} />);
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("list", { name: "Files for this flat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument(); expect(screen.queryByLabelText("Upload file")).not.toBeInTheDocument();
  });
});
