import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { RangeKey, ReportKind, ReportMap } from "../lib/reports";

export interface ReportQuery { range: RangeKey; date_from?: string; date_to?: string; project_id?: number; user_id?: number }

export function useReport<K extends ReportKind>(kind: K, q: ReportQuery, enabled = true) {
  return useQuery({
    queryKey: ["reports", kind, q],
    queryFn: async () => (await api.get<ReportMap[K]>(`/reports/${kind}`, { params: q })).data,
    // Keep showing the old figures while new ones load, but only for the same report:
    // a different report has a different shape and must not be drawn with old data.
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[1] === kind ? keepPreviousData(prev) : undefined),
    enabled,
  });
}

/** Same filters as the screen; the browser downloads it with the user's cookies. */
export function exportUrl(kind: ReportKind, q: ReportQuery): string {
  const params = new URLSearchParams(Object.entries(q).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
  return `/api/reports/${kind}/export?${params.toString()}`;
}
