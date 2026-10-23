import { CalendarClock, Handshake, Mail, MapPin, MessageCircle, Phone } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { UserBrief } from "./types";

export type TaskType = "call" | "whatsapp" | "meeting" | "site_visit" | "email" | "other";
export type TaskStatus = "pending" | "completed" | "rescheduled" | "cancelled";
export type TaskView = "today" | "overdue" | "upcoming" | "completed";

export interface Task {
  id: number;
  lead: { id: number; lead_code: string; name: string; mobile: string };
  task_type: TaskType;
  due_at: string;
  status: TaskStatus;
  is_overdue: boolean;
  notes: string | null;
  completion_note: string | null;
  completed_at: string | null;
  rescheduled_from_id: number | null;
  reschedule_reason: string | null;
  assigned_to: UserBrief | null;
  created_by: UserBrief | null;
  created_at: string;
}

export interface TaskCounts {
  today: number;
  overdue: number;
  upcoming: number;
}

export interface TaskPage {
  items: Task[];
  total: number;
  page: number;
  page_size: number;
  counts: TaskCounts;
}

export const TASK_TYPES: TaskType[] = ["call", "whatsapp", "meeting", "site_visit", "email", "other"];

export const TASK_TYPE_LABELS: Record<TaskType, string> = {
  call: "Call",
  whatsapp: "WhatsApp",
  meeting: "Meeting",
  site_visit: "Site visit",
  email: "Email",
  other: "Other",
};

export const TASK_TYPE_ICONS: Record<TaskType, LucideIcon> = {
  call: Phone,
  whatsapp: MessageCircle,
  meeting: Handshake,
  site_visit: MapPin,
  email: Mail,
  other: CalendarClock,
};

export const VIEW_LABELS: Record<TaskView, string> = {
  today: "Today",
  overdue: "Overdue",
  upcoming: "Upcoming",
  completed: "Completed",
};

const time = new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit" });
const dayMonth = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
const weekday = new Intl.DateTimeFormat("en-IN", { weekday: "short" });

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** "Today, 3:00 pm", "Tomorrow, 10:30 am", "Yesterday, 5:00 pm", "Fri 30 Oct, 11:00 am". */
export function formatDue(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const days = Math.round((startOfDay(d) - startOfDay(now)) / 86_400_000);
  const t = time.format(d);
  if (days === 0) return `Today, ${t}`;
  if (days === 1) return `Tomorrow, ${t}`;
  if (days === -1) return `Yesterday, ${t}`;
  return `${weekday.format(d)} ${dayMonth.format(d)}, ${t}`;
}

/** Value for <input type="datetime-local"> in the browser's own time zone. */
export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** datetime-local value -> ISO string with the browser's UTC offset, which the API requires. */
export function localInputToIso(value: string): string {
  return new Date(value).toISOString();
}

/** One-tap choices for when to follow up. */
export function duePresets(now = new Date()): { label: string; value: Date }[] {
  const at = (daysAhead: number, hour: number) => {
    const d = new Date(now);
    d.setDate(d.getDate() + daysAhead);
    d.setHours(hour, 0, 0, 0);
    return d;
  };
  const inTwoHours = new Date(now.getTime() + 2 * 3_600_000);
  inTwoHours.setMinutes(Math.ceil(inTwoHours.getMinutes() / 15) * 15, 0, 0);
  const daysToMonday = ((8 - now.getDay()) % 7) || 7;
  return [
    { label: "In 2 hours", value: inTwoHours },
    { label: "Tomorrow 10 am", value: at(1, 10) },
    { label: "In 2 days", value: at(2, 10) },
    { label: "Next Monday", value: at(daysToMonday, 10) },
  ];
}
