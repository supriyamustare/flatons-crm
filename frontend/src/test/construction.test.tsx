import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectMilestones } from "../components/inventory/Milestones";
import { ProjectUpdates } from "../components/inventory/ProjectUpdates";
import type { Milestone, ProjectUpdate } from "../hooks/useDemands";
import { makeUser, mockApi } from "./mockApi";
import { renderWithProviders } from "./render";

beforeEach(() => vi.restoreAllMocks());

const plinth: Milestone = { id: 3, name: "Plinth", status: "planned", completed_on: null, note: null, returned_reason: null, reported_by: null, reported_at: null,
  verified_by: null, verified_at: null, evidence: [], can_report: true, can_verify: false, percent_complete: 55, planned_on: "2026-12-15", phase: "Phase 1",
  building_label: "Habitat", responsible_pm: { id: 5, full_name: "Raj Test", role: "project_manager" }, delay_reason: "Heavy rain", revised_expected_on: "2027-01-10",
  schedule_impact: "Plinth demand moves by about a month", impact_recorded_by: { id: 5, full_name: "Raj Test", role: "project_manager" }, impact_approved_by: null,
  impact_approved_at: null, can_approve_impact: false, progress: [{ id: 1, percent_complete: 55, planned_on: null, revised_expected_on: "2027-01-10", delay_reason: "Heavy rain",
  note: "Work slowed", at: "2026-11-19T06:00:00Z", by: "Raj Test", photos: [] }] };

describe("construction progress", () => {
  it("shows percentage, delay and impact on the milestone", async () => {
    mockApi(makeUser("crm_manager"), { get: { "/projects/1/milestones": [{ ...plinth, can_approve_impact: true, can_report: false }] } });
    renderWithProviders(<ProjectMilestones projectId={1} />);
    expect(await screen.findByRole("progressbar", { name: "Plinth progress" })).toHaveAttribute("aria-valuenow", "55");
    expect(screen.getByText(/Delayed: Heavy rain. Now expected 2027-01-10/)).toBeInTheDocument();
    expect(screen.getByText("Waiting for approval")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve impact" })).toBeInTheDocument();
    expect(screen.getByText(/Progress history \(1\)/)).toBeInTheDocument();
  });

  it("a delay needs its reason and revised date; progress never raises a demand", async () => {
    const { post } = mockApi(makeUser("project_manager"), { get: { "/projects/1/milestones": [{ ...plinth, delay_reason: null, revised_expected_on: null, schedule_impact: null }] },
      post: { "/projects/1/milestones/progress": plinth } });
    renderWithProviders(<ProjectMilestones projectId={1} />);
    await userEvent.click(await screen.findByRole("button", { name: "Update progress" }));
    const d = await screen.findByRole("dialog", { name: "Update progress: Plinth" });
    expect(d).toHaveTextContent("It never raises a demand; only verified completion does.");
    await userEvent.clear(within(d).getByLabelText("Percentage complete")); await userEvent.type(within(d).getByLabelText("Percentage complete"), "60");
    await userEvent.click(within(d).getByLabelText("Delayed"));
    expect(within(d).getByRole("button", { name: "Save progress" })).toBeDisabled();
    await userEvent.type(within(d).getByLabelText("Delay reason"), "Heavy rain");
    await userEvent.type(within(d).getByLabelText("Revised expected date"), "2027-01-10");
    await userEvent.click(within(d).getByRole("button", { name: "Save progress" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const form = post.mock.calls[0][1] as FormData;
    expect([form.get("name"), form.get("percent_complete"), form.get("delay_reason"), form.get("revised_expected_on")]).toEqual(["Plinth", "60", "Heavy rain", "2027-01-10"]);
  });
});

const upd = (over: Partial<ProjectUpdate>): ProjectUpdate => ({ id: 7, title: "Plinth work under way", body: "The plinth slab is being cast this month.", status: "pending_approval",
  milestone: "Plinth", author: "Raj Test", created_at: "2026-11-19T06:00:00Z", published_at: null, published_by: null, returned_reason: null, photos: [], corrections: [],
  can_edit: false, can_publish: false, can_correct: false, ...over });

describe("customer updates", () => {
  it("the author waits for someone else; an approver publishes", async () => {
    mockApi(makeUser("project_manager"), { get: { "/projects/1/updates": [upd({ can_edit: true })], "/projects/1/milestones": [plinth] } });
    const { unmount } = renderWithProviders(<ProjectUpdates projectId={1} />);
    expect(await screen.findByText("Someone other than the author publishes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    unmount(); vi.restoreAllMocks();
    const { post } = mockApi(makeUser("crm_manager"), { get: { "/projects/1/updates": [upd({ can_publish: true })], "/projects/1/milestones": [plinth] },
      post: { "/project-updates/7/publish": [upd({ status: "published", published_at: "2026-11-19T07:00:00Z", published_by: "Meera Test", can_correct: true })] } });
    renderWithProviders(<ProjectUpdates projectId={1} />);
    await userEvent.click(await screen.findByRole("button", { name: "Publish" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/project-updates/7/publish", undefined));
    expect(await screen.findByText("Published")).toBeInTheDocument();
  });

  it("a correction asks for the reason and shows the earlier wording", async () => {
    const pub = upd({ status: "published", published_at: "2026-11-19T07:00:00Z", published_by: "Meera Test", can_correct: true,
      corrections: [{ at: "2026-11-20T05:00:00Z", by: "Meera Test", reason: "Revised date from the site", previous_title: "Plinth work under way", previous_body: "Completion in January." }] });
    const { post } = mockApi(makeUser("crm_manager"), { get: { "/projects/1/updates": [pub], "/projects/1/milestones": [plinth] }, post: { "/project-updates/7/correct": [pub] } });
    renderWithProviders(<ProjectUpdates projectId={1} />);
    expect(await screen.findByText(/Corrections \(1\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Correct" }));
    const d = await screen.findByRole("dialog", { name: "Correct the published update" });
    expect(within(d).getByRole("button", { name: "Publish correction" })).toBeDisabled();
    await userEvent.type(within(d).getByLabelText("Reason for the correction"), "Typo in the month");
    await userEvent.click(within(d).getByRole("button", { name: "Publish correction" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/project-updates/7/correct", expect.objectContaining({ reason: "Typo in the month" })));
  });
});
