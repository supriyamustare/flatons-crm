import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ArrowRightLeft, CalendarPlus, Phone, Plus, Search, SlidersHorizontal, StickyNote } from "lucide-react";
import { StatusBadge } from "../../components/leads/LeadBits";
import { NoteDialog, StatusDialog } from "../../components/leads/LeadDialogs";
import { NewTaskDialog } from "../../components/tasks/TaskDialogs";
import { Button, ErrorState, PageHeader } from "../../components/ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { useLeadSearch } from "../../hooks/useLeads";
import type { LeadQuery } from "../../hooks/useLeads";
import { errorMessage, formatDateTime } from "../../lib/api";
import { EMPTY_FILTERS, SOURCE_LABELS, countActiveFilters, formatBudget, formatMobile } from "../../lib/leads";
import type { Lead, LeadFilters } from "../../lib/leads";
import { FilterDialog } from "./LeadFilters";

const SORTS = {
  newest: { sort: "created_at", order: "desc", label: "Newest first" },
  oldest: { sort: "created_at", order: "asc", label: "Oldest first" },
  active: { sort: "last_activity_at", order: "desc", label: "Recently active" },
  stale: { sort: "last_activity_at", order: "asc", label: "Longest without activity" },
  name: { sort: "name", order: "asc", label: "Name A–Z" },
} as const;
type SortKey = keyof typeof SORTS;
const PAGE_SIZE = 25;

/** List state survives opening a lead and coming back. Kept in sessionStorage (this tab only),
 *  not the URL, so searched phone numbers never reach server access logs. */
const STATE_KEY = "flatons.leads.list";
interface ListState { search: string; filters: LeadFilters; sortKey: SortKey; page: number }
function loadState(): ListState {
  const fallback: ListState = { search: "", filters: EMPTY_FILTERS, sortKey: "newest", page: 1 };
  try {
    const saved = JSON.parse(sessionStorage.getItem(STATE_KEY) ?? "null") as Partial<ListState> | null;
    if (!saved) return fallback;
    return {
      search: typeof saved.search === "string" ? saved.search : "",
      filters: { ...EMPTY_FILTERS, ...saved.filters },
      sortKey: saved.sortKey && saved.sortKey in SORTS ? saved.sortKey : "newest",
      page: typeof saved.page === "number" && saved.page > 0 ? saved.page : 1,
    };
  } catch {
    return fallback;
  }
}

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function QuickActions({ lead, canEdit, onStatus, onNote, onTask }: {
  lead: Lead; canEdit: boolean; onStatus: () => void; onNote: () => void; onTask: () => void;
}) {
  const btn = "grid size-11 place-items-center rounded-lg text-forest-800 hover:bg-forest-50";
  return (
    <div className="flex items-center gap-1">
      <a href={`tel:${lead.mobile}`} className={btn} aria-label={`Call ${lead.name}`} title="Call">
        <Phone className="size-[18px]" />
      </a>
      {canEdit && (
        <>
          <button type="button" onClick={onTask} className={btn} aria-label={`Add follow-up for ${lead.name}`} title="Add follow-up">
            <CalendarPlus className="size-[18px]" />
          </button>
          <button type="button" onClick={onNote} className={btn} aria-label={`Add note for ${lead.name}`} title="Add note">
            <StickyNote className="size-[18px]" />
          </button>
          <button type="button" onClick={onStatus} className={btn} aria-label={`Change status for ${lead.name}`} title="Change status">
            <ArrowRightLeft className="size-[18px]" />
          </button>
        </>
      )}
    </div>
  );
}

export function LeadsPage() {
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const canCreate = me.role !== "docs";
  const canEdit = (l: Lead) => isManager || (me.role === "executive" && l.assigned_to?.id === me.id);

  const [initial] = useState(loadState);
  const [search, setSearch] = useState(initial.search);
  const [filters, setFilters] = useState<LeadFilters>(initial.filters);
  const [sortKey, setSortKey] = useState<SortKey>(initial.sortKey);
  const [page, setPage] = useState(initial.page);
  const [showFilters, setShowFilters] = useState(false);
  const [dialog, setDialog] = useState<{ kind: "status" | "note" | "task"; lead: Lead } | null>(null);

  const q = useDebounced(search.trim());
  // Back to page 1 when the search, filters or sort change (but not on first render,
  // so a restored page number is kept).
  const [criteria, setCriteria] = useState({ q, filters, sortKey });
  if (criteria.q !== q || criteria.filters !== filters || criteria.sortKey !== sortKey) {
    setCriteria({ q, filters, sortKey });
    setPage(1);
  }
  useEffect(() => {
    try {
      sessionStorage.setItem(STATE_KEY, JSON.stringify({ search, filters, sortKey, page }));
    } catch {
      /* storage full or blocked: the list still works, it just won't be remembered */
    }
  }, [search, filters, sortKey, page]);

  const query: LeadQuery = {
    ...filters, q: q || undefined, sort: SORTS[sortKey].sort, order: SORTS[sortKey].order, page, page_size: PAGE_SIZE,
  };
  const leads = useLeadSearch(query);
  const activeFilters = countActiveFilters(filters);
  const total = leads.data?.total ?? 0;
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);
  const anyFilter = Boolean(q) || activeFilters > 0;

  return (
    <>
      <PageHeader
        title="Leads"
        description={me.role === "executive" ? "Leads assigned to you" : undefined}
        action={canCreate && (
          <Link to="/leads/new" className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white hover:bg-forest-800">
            <Plus className="size-4" aria-hidden /> New lead
          </Link>
        )}
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <label className="relative min-w-0 flex-1 basis-60">
          <span className="sr-only">Search leads</span>
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Name, phone or lead ID"
            className="block min-h-11 w-full rounded-lg border border-line bg-white pr-3 pl-9 text-base focus:border-forest-700 focus:ring-2 focus:ring-forest-700/20 focus:outline-none md:text-sm"
          />
        </label>
        <Button variant="secondary" onClick={() => setShowFilters(true)}>
          <SlidersHorizontal className="size-4" aria-hidden />
          Filters{activeFilters > 0 && ` (${activeFilters})`}
        </Button>
        <label className="sr-only" htmlFor="lead-sort">Sort</label>
        <select
          id="lead-sort"
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          className="min-h-11 rounded-lg border border-line bg-white px-3 text-sm"
        >
          {Object.entries(SORTS).map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
        </select>
      </div>

      {leads.isPending && (
        <div className="space-y-2" aria-busy="true" aria-label="Loading leads">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-16 animate-pulse rounded-xl bg-white" />)}
        </div>
      )}
      {leads.isError && <ErrorState message={errorMessage(leads.error, "Couldn’t load leads.")} onRetry={() => void leads.refetch()} />}

      {leads.isSuccess && total === 0 && (
        <div className="rounded-xl border border-dashed border-line bg-white px-6 py-12 text-center">
          {anyFilter ? (
            <>
              <p className="font-medium text-ink">No leads match these filters</p>
              <Button variant="ghost" className="mt-3" onClick={() => { setSearch(""); setFilters(EMPTY_FILTERS); }}>
                Clear search and filters
              </Button>
            </>
          ) : (
            <>
              <p className="font-display text-xl text-forest-900">No leads yet</p>
              <p className="mt-1 text-sm text-muted">
                {canCreate ? "Add your first enquiry to start tracking it." : "Leads will appear here once the sales team adds them."}
              </p>
              {canCreate && (
                <Link to="/leads/new" className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white">
                  <Plus className="size-4" aria-hidden /> Add a lead
                </Link>
              )}
            </>
          )}
        </div>
      )}

      {leads.isSuccess && total > 0 && (
        <div className={leads.isPlaceholderData ? "opacity-60 transition-opacity" : ""}>
          {/* Phones */}
          <ul className="space-y-2 md:hidden">
            {leads.data.items.map((l) => (
              <li key={l.id} className="rounded-xl border border-line bg-white">
                <Link to={`/leads/${l.id}`} className="block px-4 pt-3.5 pb-2">
                  <div className="flex items-start justify-between gap-3">
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-ink">{l.name}</span>
                      <span className="block text-sm text-muted">{formatMobile(l.mobile)}</span>
                    </span>
                    <StatusBadge status={l.status} />
                  </div>
                  <p className="mt-1.5 truncate text-xs text-muted">
                    {[l.project?.name, formatBudget(l.budget_min, l.budget_max), SOURCE_LABELS[l.source]]
                      .filter((x) => x && x !== "—").join(", ")}
                  </p>
                </Link>
                <div className="flex items-center justify-between border-t border-line px-2">
                  <span className="px-2 text-xs text-muted">{l.assigned_to?.full_name ?? "Unassigned"}</span>
                  <QuickActions lead={l} canEdit={canEdit(l)}
                    onStatus={() => setDialog({ kind: "status", lead: l })}
                    onNote={() => setDialog({ kind: "note", lead: l })}
                    onTask={() => setDialog({ kind: "task", lead: l })} />
                </div>
              </li>
            ))}
          </ul>

          {/* Tablets and desktop */}
          <div className="hidden overflow-x-auto rounded-xl border border-line bg-white md:block">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line whitespace-nowrap text-muted">
                <tr>
                  <th className="px-4 py-3 font-medium">Lead</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Project and budget</th>
                  <th className="px-4 py-3 font-medium">Source</th>
                  {isManager && <th className="px-4 py-3 font-medium">Assigned to</th>}
                  <th className="px-4 py-3 font-medium">Last activity</th>
                  <th className="px-4 py-3"><span className="sr-only">Quick actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {leads.data.items.map((l) => (
                  <tr key={l.id} className="hover:bg-paper/60">
                    <td className="px-4 py-3">
                      <Link to={`/leads/${l.id}`} className="font-medium text-ink hover:underline">{l.name}</Link>
                      <div className="text-xs whitespace-nowrap text-muted">{formatMobile(l.mobile)}</div>
                      <div className="text-xs whitespace-nowrap text-muted">{l.lead_code}</div>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={l.status} /></td>
                    <td className="px-4 py-3">
                      <div>{l.project?.name ?? "—"}</div>
                      <div className="text-xs text-muted">{formatBudget(l.budget_min, l.budget_max)}</div>
                    </td>
                    <td className="px-4 py-3">{SOURCE_LABELS[l.source]}</td>
                    {isManager && <td className="px-4 py-3 whitespace-nowrap">{l.assigned_to?.full_name ?? <span className="text-muted">Unassigned</span>}</td>}
                    <td className="px-4 py-3 whitespace-nowrap text-muted">{formatDateTime(l.last_activity_at)}</td>
                    <td className="px-2 py-1">
                      <QuickActions lead={l} canEdit={canEdit(l)}
                        onStatus={() => setDialog({ kind: "status", lead: l })}
                        onNote={() => setDialog({ kind: "note", lead: l })}
                    onTask={() => setDialog({ kind: "task", lead: l })} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex items-center justify-between text-sm text-muted">
            <span>{from}–{to} of {total}</span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <Button variant="secondary" disabled={to >= total} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          </div>
        </div>
      )}

      {showFilters && (
        <FilterDialog value={filters} onApply={setFilters} onClose={() => setShowFilters(false)} canFilterByPerson={isManager} />
      )}
      {dialog?.kind === "status" && <StatusDialog lead={dialog.lead} onClose={() => setDialog(null)} />}
      {dialog?.kind === "note" && <NoteDialog lead={dialog.lead} onClose={() => setDialog(null)} />}
      {dialog?.kind === "task" && (
        <NewTaskDialog lead={{ id: dialog.lead.id, name: dialog.lead.name, assigned_to_id: dialog.lead.assigned_to?.id }} onClose={() => setDialog(null)} />
      )}
    </>
  );
}

