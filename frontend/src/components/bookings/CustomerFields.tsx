import { SelectInput, TextArea, TextInput } from "../ui";
import type { CustomerDetails, PaymentPreference } from "../../lib/bookings";

export type CustomerForm = Record<keyof CustomerDetails, string>;
export const emptyCustomer = (c?: Partial<CustomerDetails> | null): CustomerForm => ({
  customer_name: c?.customer_name ?? "", applicant_name: c?.applicant_name ?? "", customer_mobile: c?.customer_mobile ?? "",
  customer_email: c?.customer_email ?? "", customer_address: c?.customer_address ?? "", payment_preference: c?.payment_preference ?? "",
  bank_name: c?.bank_name ?? "", banker_name: c?.banker_name ?? "", banker_phone: c?.banker_phone ?? "",
});
/** Only send bank details with bank payment; blank fields go as null. */
export function customerPayload(f: CustomerForm) {
  const bank = f.payment_preference === "bank";
  const v = (x: string) => x.trim() || null;
  return {
    customer_name: v(f.customer_name), applicant_name: v(f.applicant_name), customer_mobile: v(f.customer_mobile),
    customer_email: v(f.customer_email), customer_address: v(f.customer_address),
    payment_preference: (f.payment_preference || null) as PaymentPreference | null,
    bank_name: bank ? v(f.bank_name) : null, banker_name: bank ? v(f.banker_name) : null, banker_phone: bank ? v(f.banker_phone) : null,
  };
}

/** Customer details and payment preference (self or bank loan with bank name and banker contact). */
export function CustomerFields({ f, set }: { f: CustomerForm; set: (patch: Partial<CustomerForm>) => void }) {
  return (
    <fieldset className="space-y-3">
      <legend className="mb-1 text-sm font-semibold">Customer</legend>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <TextInput label="Name" value={f.customer_name} onChange={(e) => set({ customer_name: e.target.value })} maxLength={150} />
        <TextInput label="Applicant name" value={f.applicant_name} onChange={(e) => set({ applicant_name: e.target.value })} maxLength={150}
          hint="As on the agreement, including any co-applicant" />
        <TextInput label="Mobile number" type="tel" value={f.customer_mobile} onChange={(e) => set({ customer_mobile: e.target.value })} maxLength={20} />
        <TextInput label="Email ID" type="email" value={f.customer_email} onChange={(e) => set({ customer_email: e.target.value })} maxLength={254} />
      </div>
      <TextArea label="Address" value={f.customer_address} onChange={(e) => set({ customer_address: e.target.value })} maxLength={500} rows={2} />
      <SelectInput label="Payment preference" value={f.payment_preference} onChange={(e) => set({ payment_preference: e.target.value })}>
        <option value="">Not decided</option>
        <option value="self">Self payment</option>
        <option value="bank">Bank payment (home loan)</option>
      </SelectInput>
      {f.payment_preference === "bank" && (
        <div className="grid grid-cols-1 gap-3 rounded-lg bg-paper p-3 sm:grid-cols-2">
          <TextInput label="Bank name" value={f.bank_name} onChange={(e) => set({ bank_name: e.target.value })} maxLength={150} placeholder="e.g. HDFC Bank" />
          <TextInput label="Banker contact person" value={f.banker_name} onChange={(e) => set({ banker_name: e.target.value })} maxLength={150} />
          <TextInput label="Banker phone" type="tel" value={f.banker_phone} onChange={(e) => set({ banker_phone: e.target.value })} maxLength={20} />
        </div>
      )}
    </fieldset>
  );
}

export const PREFERENCE_LABELS: Record<PaymentPreference, string> = { self: "Self payment", bank: "Bank payment (home loan)" };
