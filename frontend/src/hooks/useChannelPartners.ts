import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { LeadStatus } from "../lib/leads";
import type { UserBrief } from "../lib/types";

export interface ChannelPartner {
  id: number; name: string; company_name: string | null; mobile: string; email: string | null; rera_number: string | null;
  notes: string | null; is_active: boolean; created_at: string; leads: number; bookings: number; booked_value: number;
}
export interface PartnerCustomer {
  lead_id: number; lead_code: string; name: string; mobile: string; status: LeadStatus; project: string | null; owner: UserBrief | null;
  created_at: string; booking_id: number | null; booking_code: string | null; unit_no: string | null; booked_project: string | null;
  agreed_price: number | null; booking_date: string | null;
}
export interface PartnerInput { name: string; company_name: string | null; mobile: string; email: string | null; rera_number: string | null; notes: string | null }

export function useChannelPartners(q = "", includeInactive = false) {
  return useQuery({
    queryKey: ["channel-partners", "list", q, includeInactive],
    queryFn: async () => (await api.get<ChannelPartner[]>("/channel-partners", { params: { q: q || undefined, include_inactive: includeInactive || undefined, page_size: 200 } })).data,
    placeholderData: keepPreviousData,
  });
}
export function useChannelPartner(id: number) {
  return useQuery({ queryKey: ["channel-partners", id], queryFn: async () => (await api.get<ChannelPartner>(`/channel-partners/${id}`)).data, enabled: id > 0 });
}
export function usePartnerCustomers(id: number) {
  return useQuery({
    queryKey: ["channel-partners", id, "customers"],
    queryFn: async () => (await api.get<{ items: PartnerCustomer[]; total: number }>(`/channel-partners/${id}/customers`, { params: { page_size: 200 } })).data,
    enabled: id > 0,
  });
}
export function useSavePartner() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: Partial<PartnerInput> & { id?: number; is_active?: boolean }) =>
      (id ? await api.patch<ChannelPartner>(`/channel-partners/${id}`, body) : await api.post<ChannelPartner>("/channel-partners", body)).data,
    onSettled: () => void qc.invalidateQueries({ queryKey: ["channel-partners"] }),
  });
}
