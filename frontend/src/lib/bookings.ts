import type { UnitType } from "./inventory";
import type { UserBrief } from "./types";

export type BookingStatus = "booked" | "cancelled";
export type PaymentPreference = "self" | "bank";
export interface CustomerDetails {
  customer_name: string | null; applicant_name: string | null; customer_mobile: string | null; customer_email: string | null;
  customer_address: string | null; payment_preference: PaymentPreference | null; bank_name: string | null; banker_name: string | null; banker_phone: string | null;
}
export type PaymentMode = "cheque" | "bank_transfer" | "upi" | "card" | "cash" | "other";

export interface Booking {
  id: number; booking_code: string; status: BookingStatus;
  lead: { id: number; lead_code: string; name: string; mobile: string; email: string | null; city: string | null };
  project: { id: number; name: string };
  unit: { id: number; unit_no: string; unit_type: UnitType; building: string | null; floor_number: number | null;
    carpet_sqft: string | null; builtup_sqft: string | null; address_note: string | null };
  booking_date: string; agreed_price: number; booking_amount: number; balance: number;
  payment_mode: PaymentMode | null; payment_reference: string | null; channel_partner: string | null;
  commission_pct: string | null; commission_expected: number | null; commission_received: number; notes: string | null;
  sales_exec: UserBrief | null; recorded_by: UserBrief | null; customer: CustomerDetails; created_at: string;
  cancelled_at: string | null; cancellation_reason: string | null;
  history: { at: string; action: string; actor: UserBrief | null; details: Record<string, unknown> | null }[];
}

export interface MissingDetails {
  lead_id: number; lead_code: string; name: string; mobile: string; project: { id: number; name: string } | null;
  assigned_to: UserBrief | null; booked_since: string;
}

export interface BookingPage {
  items: Booking[]; total: number; page: number; page_size: number;
  totals: { count: number; agreed_value: number; booking_amount: number; commission_expected: number; commission_received: number };
  missing_details: MissingDetails[];
}

export const PAYMENT_MODES: PaymentMode[] = ["cheque", "bank_transfer", "upi", "card", "cash", "other"];
export const PAYMENT_LABELS: Record<PaymentMode, string> = {
  cheque: "Cheque", bank_transfer: "Bank transfer (NEFT / RTGS / IMPS)", upi: "UPI", card: "Card", cash: "Cash", other: "Other",
};
export const HISTORY_LABELS: Record<string, string> = {
  created: "Booking recorded", customer_updated: "Customer details updated", edited: "Details changed", commission_received: "Commission received updated", cancelled: "Booking cancelled",
};
