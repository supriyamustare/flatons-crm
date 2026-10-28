import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Booking, BookingPage, BookingStatus, PaymentMode } from "../lib/bookings";

export interface BookingQuery { status?: BookingStatus | ""; project_id?: number; sales_exec_id?: number; date_from?: string; date_to?: string; page?: number }

export function useBookings(q: BookingQuery) {
  const params = { ...q, status: q.status === "" ? undefined : q.status };
  return useQuery({
    queryKey: ["bookings", "list", params],
    queryFn: async () => (await api.get<BookingPage>("/bookings", { params })).data,
    placeholderData: keepPreviousData,
  });
}

export function useBooking(id: number) {
  return useQuery({
    queryKey: ["bookings", id],
    queryFn: async () => (await api.get<Booking>(`/bookings/${id}`)).data,
    enabled: id > 0, // nothing to fetch for a unit without a booking
  });
}

function useBookingMutation<V>(fn: (v: V) => Promise<Booking>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (b) => qc.setQueryData(["bookings", b.id], b),
    onSettled: () => {
      for (const key of [["bookings"], ["leads"], ["lead"], ["inventory"], ["projects"], ["dashboard"], ["pipeline"]]) void qc.invalidateQueries({ queryKey: key });
    },
  });
}

export interface NewBooking {
  lead_id: number; unit_id: number; booking_date: string; agreed_price: number; booking_amount: number;
  payment_mode?: PaymentMode; payment_reference?: string; channel_partner?: string; notes?: string; sales_exec_id?: number;
  customer?: Record<string, string | null>;
}
export const useCreateBooking = () => useBookingMutation(async (b: NewBooking) => (await api.post<Booking>("/bookings", b)).data);
export const useUpdateBooking = () =>
  useBookingMutation(async ({ id, ...body }: { id: number } & Record<string, unknown>) => (await api.patch<Booking>(`/bookings/${id}`, body)).data);
export const useCancelBooking = () =>
  useBookingMutation(async ({ id, reason }: { id: number; reason: string }) => (await api.post<Booking>(`/bookings/${id}/cancel`, { reason })).data);

export const bookingsExportUrl = (q: BookingQuery) => {
  const p = new URLSearchParams(Object.entries(q).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
  return `/api/bookings/export?${p.toString()}`;
};

export const useUpdateCustomer = () =>
  useBookingMutation(async ({ id, ...body }: { id: number } & Record<string, unknown>) =>
    (await api.patch<Booking>(`/bookings/${id}/customer`, body)).data);
