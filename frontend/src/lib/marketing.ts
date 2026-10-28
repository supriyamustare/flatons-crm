import type { UserBrief } from "./types";

export type Channel = "google_ads" | "social" | "99acres" | "magicbricks" | "housing" | "website" | "print" | "event" | "sms_email" | "channel_partner" | "other";
export type ExpenseCategory = "ad_spend" | "agency_fee" | "printing" | "event" | "listing_fee" | "other";

export interface Campaign {
  id: number; name: string; channel: Channel; project: { id: number; name: string } | null;
  start_date: string; end_date: string | null; description: string | null; created_at: string;
}

export interface Expense {
  id: number; campaign: { id: number; name: string; channel: Channel }; spent_on: string; amount: number;
  category: ExpenseCategory; vendor: string | null; notes: string | null; has_receipt: boolean;
  receipt_name: string | null; entered_by: UserBrief | null; created_at: string;
}

export interface ExpensePage {
  items: Expense[]; total: number; page: number; page_size: number; total_amount: number;
  by_channel: Partial<Record<Channel, number>>;
}

export const CHANNELS: Channel[] = ["google_ads", "social", "99acres", "magicbricks", "housing", "print", "event", "channel_partner", "other"];
export const CHANNEL_LABELS: Record<Channel, string> = {
  google_ads: "Google Ads", social: "Meta ads (Facebook / Instagram)", "99acres": "99acres", magicbricks: "MagicBricks",
  housing: "Housing.com", website: "Website", print: "Print / hoardings", event: "Event / expo",
  sms_email: "SMS / email", channel_partner: "Channel partner", other: "Other",
};
export const CATEGORIES: ExpenseCategory[] = ["ad_spend", "agency_fee", "printing", "event", "listing_fee", "other"];
export const CATEGORY_LABELS: Record<ExpenseCategory, string> = {
  ad_spend: "Ad spend", agency_fee: "Agency fee", printing: "Printing", event: "Event cost", listing_fee: "Listing fee", other: "Other",
};

export function campaignIsActive(c: Campaign, today = new Date()): boolean {
  const iso = today.toISOString().slice(0, 10);
  return c.start_date <= iso && (!c.end_date || c.end_date >= iso);
}

export const RECEIPT_TYPES = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";
export const RECEIPT_MAX_BYTES = 10 * 1024 * 1024;
