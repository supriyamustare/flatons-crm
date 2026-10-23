import type { UserBrief } from "./types";

export type CallOutcome =
  | "interested" | "callback" | "not_interested"
  | "no_answer" | "busy" | "unreachable" | "wrong_number";
export type CallDirection = "outgoing" | "incoming";

export interface Call {
  id: number;
  lead: { id: number; lead_code: string; name: string; mobile: string };
  user: UserBrief | null;
  direction: CallDirection;
  outcome: CallOutcome;
  connected: boolean;
  duration_sec: number | null;
  notes: string | null;
  called_at: string;
  follow_up_task_id: number | null;
}

export interface CallPage {
  items: Call[];
  total: number;
  page: number;
  page_size: number;
  connected: number;
}

export const CONNECTED: CallOutcome[] = ["interested", "callback", "not_interested"];
export const NOT_CONNECTED: CallOutcome[] = ["no_answer", "busy", "unreachable", "wrong_number"];

export const OUTCOME_LABELS: Record<CallOutcome, string> = {
  interested: "Interested",
  callback: "Call back later",
  not_interested: "Not interested",
  no_answer: "No answer",
  busy: "Busy",
  unreachable: "Switched off / unreachable",
  wrong_number: "Wrong number",
};

/** 245 -> "4 min 5 s"; null -> "" */
export function formatDuration(sec: number | null): string {
  if (sec === null || sec === undefined) return "";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m === 0) return `${s} s`;
  return s ? `${m} min ${s} s` : `${m} min`;
}
