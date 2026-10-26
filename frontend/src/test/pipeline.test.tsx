import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LeadStatus } from "../lib/leads";
import type { PipelineBoard, PipelineCard } from "../lib/pipeline";
import { daysInStageLabel } from "../lib/pipeline";
import { makeUser, mockApi } from "./mockApi";
import { renderApp } from "./render";

function card(id: number, name: string, status: LeadStatus, extra: Partial<PipelineCard> = {}): PipelineCard {
  return { id, lead_code: `LEAD-${id}`, name, status, project: { id: 1, name: "Green Meadows" }, budget_min: 6_000_000,
    budget_max: 7_500_000, deal_value: 7_500_000, assigned_to: { id: 7, full_name: "Ravi Kumar", role: "executive" },
    days_in_stage: 3, stale: false, last_activity_at: "2026-10-25T05:00:00Z", ...extra };
}

const STAGES: LeadStatus[] = ["new", "not_reachable", "contacted", "qualified", "follow_up", "visit_scheduled", "visit_done", "revisit", "negotiation", "on_hold", "booked"];

function board(cards: PipelineCard[]): PipelineBoard {
  return {
    stale_after_days: 7,
    stages: STAGES.map((s) => {
      const cs = cards.filter((c) => c.status === s);
      const value = cs.reduce((a, c) => a + (c.deal_value ?? 0), 0);
      return { stage: s, probability_pct: s === "negotiation" ? 70 : 10, count: cs.length, value, weighted_value: Math.round(value * (s === "negotiation" ? 0.7 : 0.1)),
        stale_count: cs.filter((c) => c.stale).length, missing_value_count: 0, cards: cs, has_more: false };
    }),
    totals: { open_count: 2, open_value: 15_000_000, weighted_value: 6_000_000, booked_count: 0, booked_value: 0, stale_count: 1, missing_value_count: 0 },
  };
}

const cards = [card(1, "Anita Desai", "negotiation"), card(2, "Vikram Joshi", "contacted", { stale: true, days_in_stage: 12 })];
const forecast = { by_project: [], by_executive: [], total: { count: 0, value: 0, weighted_value: 0 } };

beforeEach(() => vi.restoreAllMocks());

describe("pipeline", () => {
  it("formats days in stage", () => {
    expect(daysInStageLabel(0)).toBe("Today");
    expect(daysInStageLabel(1)).toBe("1 day");
    expect(daysInStageLabel(12)).toBe("12 days");
  });

  it("shows columns with weighted values and flags quiet leads", async () => {
    mockApi(makeUser("manager"), { get: { "/pipeline": board(cards), "/pipeline/forecast": forecast } });
    renderApp("/pipeline");

    const nego = await screen.findByRole("region", { name: "Negotiation, 1 leads" });
    expect(nego).toHaveTextContent("(70%)");
    expect(within(nego).getByRole("article", { name: "Anita Desai, Negotiation" })).toBeInTheDocument();
    const quiet = screen.getByRole("article", { name: /Vikram Joshi, Contacted, no activity for over a week/ });
    expect(within(quiet).getByText(/12 days in stage · quiet/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Forecast" })).getByText("Weighted forecast")).toBeInTheDocument();
  });

  it("moves a card without dragging, using the Move to menu", async () => {
    let current = cards;
    const { patch } = mockApi(makeUser("manager"), {
      get: { "/pipeline": () => board(current), "/pipeline/forecast": forecast },
      patch: { "/leads/2/pipeline": () => { current = cards.map((c) => (c.id === 2 ? { ...c, status: "qualified" as const } : c)); return {}; } },
    });
    renderApp("/pipeline");

    await userEvent.selectOptions(await screen.findByLabelText("Move Vikram Joshi to"), "qualified");

    await waitFor(() => expect(patch).toHaveBeenCalledWith("/leads/2/pipeline", { status: "qualified", reason: undefined }));
    // moved on screen straight away
    await waitFor(() => expect(within(screen.getByRole("region", { name: /^Qualified/ })).getByText("Vikram Joshi")).toBeInTheDocument());
  });

  it("asks for a reason before moving to Lost", async () => {
    const { patch } = mockApi(makeUser("manager"), {
      get: { "/pipeline": board(cards), "/pipeline/forecast": forecast }, patch: { "/leads/1/pipeline": {} },
    });
    renderApp("/pipeline");
    // Lost is in the menu even while the Lost column is hidden
    await userEvent.selectOptions(await screen.findByLabelText("Move Anita Desai to"), "lost");

    const dialog = await screen.findByRole("dialog", { name: "Move Anita Desai to Lost" });
    expect(within(dialog).getByRole("button", { name: "Move lead" })).toBeDisabled();
    expect(patch).not.toHaveBeenCalled();
    await userEvent.type(within(dialog).getByLabelText("Why was this lead lost?"), "Bought elsewhere");
    await userEvent.click(within(dialog).getByRole("button", { name: "Move lead" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/leads/1/pipeline", { status: "lost", reason: "Bought elsewhere" }));
  });

  it("tells an executive that booking is for managers, without calling the server", async () => {
    const { patch } = mockApi(makeUser("executive"), { get: { "/pipeline": board(cards), "/pipeline/forecast": forecast } });
    renderApp("/pipeline");
    await userEvent.selectOptions(await screen.findByLabelText("Move Anita Desai to"), "booked");
    expect(await screen.findByRole("alert")).toHaveTextContent("Only managers and admins can mark a lead as booked.");
    expect(patch).not.toHaveBeenCalled();
  });

  it("puts the card back and explains if the server refuses", async () => {
    const { AxiosError, AxiosHeaders } = await import("axios");
    const config = { headers: new AxiosHeaders() };
    const err = new AxiosError("x", "409", config, null, { status: 409, statusText: "", data: { detail: "Someone else just changed this lead" }, headers: {}, config });
    mockApi(makeUser("manager"), {
      get: { "/pipeline": board(cards), "/pipeline/forecast": forecast }, patch: { "/leads/2/pipeline": () => { throw err; } },
    });
    renderApp("/pipeline");
    await userEvent.selectOptions(await screen.findByLabelText("Move Vikram Joshi to"), "qualified");
    expect(await screen.findByRole("alert")).toHaveTextContent("Someone else just changed this lead");
    await waitFor(() => expect(within(screen.getByRole("region", { name: /^Contacted/ })).getByText("Vikram Joshi")).toBeInTheDocument());
  });

  it("only admins can edit probabilities", async () => {
    mockApi(makeUser("manager"), { get: { "/pipeline": board(cards), "/pipeline/forecast": forecast } });
    renderApp("/pipeline");
    await screen.findByRole("region", { name: "Forecast" });
    expect(screen.queryByRole("button", { name: "Probabilities" })).not.toBeInTheDocument();
  });
});

describe("keyboard moving on the board", () => {
  it("Space, three rapid Right presses, Space: moves exactly three columns", async () => {
    const { patch } = mockApi(makeUser("manager"), {
      get: { "/pipeline": board([card(5, "Priya Kulkarni", "new")]), "/pipeline/forecast": forecast }, patch: { "/leads/5/pipeline": {} },
    });
    renderApp("/pipeline");
    const grip = await screen.findByRole("button", { name: /^Move Priya Kulkarni: press Space/ });
    grip.focus();
    await userEvent.keyboard(" ");
    expect(screen.getByText(/^Picked up Priya Kulkarni, in New/)).toBeInTheDocument();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
    expect(screen.getByText("Over Qualified.")).toBeInTheDocument();
    await userEvent.keyboard(" ");
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/leads/5/pipeline", { status: "qualified", reason: undefined }));
  });

  it("Escape cancels without moving", async () => {
    const { patch } = mockApi(makeUser("manager"), {
      get: { "/pipeline": board([card(5, "Priya Kulkarni", "new")]), "/pipeline/forecast": forecast },
    });
    renderApp("/pipeline");
    const grip = await screen.findByRole("button", { name: /^Move Priya Kulkarni: press Space/ });
    grip.focus();
    await userEvent.keyboard(" {ArrowRight}{Escape}");
    expect(screen.getByText("Move cancelled.")).toBeInTheDocument();
    expect(patch).not.toHaveBeenCalled();
  });
});
