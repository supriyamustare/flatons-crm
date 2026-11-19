import { useState } from "react";
import { Link } from "react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Badge, Button, ErrorState, SelectInput, cx } from "../../components/ui";
import { STATUS, fmtTime, useCalendar } from "../../hooks/useAppointments";
import type { CalItem } from "../../hooks/useAppointments";
import { errorMessage } from "../../lib/api";

const ist = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
function monday(d: Date) { const x = new Date(ist(d) + "T00:00:00"); const wd = (x.getDay() + 6) % 7; x.setDate(x.getDate() - wd); return x; }
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };

function Item({ i }: { i: CalItem }) {
  const done = i.status === "attended" || i.status === "completed";
  return (
    <Link to={i.link} className={cx("block rounded-lg p-2 text-xs ring-1 hover:ring-forest-700", i.status === "no_show" ? "bg-danger-soft ring-danger/30" : done ? "bg-paper ring-line" : i.source === "sales_visit" ? "bg-gold-100/60 ring-gold-300" : "bg-forest-50 ring-forest-100")}>
      <span className="font-semibold">{fmtTime(i.starts_at)}</span> · {i.label}
      <span className="block truncate font-medium text-ink">{i.customer}{i.case_code ? ` (${i.case_code})` : ""}</span>
      {i.location && <span className="block truncate text-muted">{i.location}</span>}
      <span className="mt-0.5 flex flex-wrap gap-1">
        {i.status !== "scheduled" && <Badge tone={i.status === "no_show" ? "gold" : "muted"}>{STATUS[i.status] ?? i.status}</Badge>}
        {i.status === "scheduled" && i.source === "appointment" && <Badge tone={i.confirmed ? "neutral" : "gold"}>{i.confirmed ? "Confirmed" : "Not confirmed"}</Badge>}
        {i.owner && <span className="text-muted">{i.owner}</span>}
      </span>
    </Link>
  );
}

export function CalendarPage() {
  const [start, setStart] = useState(() => monday(new Date()));
  const [mine, setMine] = useState(false);
  const [kind, setKind] = useState("");
  const q = useCalendar(ist(start), 7, mine);
  const days = Array.from({ length: 7 }, (_, n) => addDays(start, n));
  const items = (q.data ?? []).filter((i) => !kind || i.kind === kind);
  const byDay = (d: Date) => items.filter((i) => ist(new Date(i.starts_at)) === ist(d));
  const today = ist(new Date());
  const kinds = Array.from(new Map((q.data ?? []).map((i) => [i.kind, i.label.replace(" (sales)", "")])).entries());
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl text-forest-900 sm:text-3xl">Calendar</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" aria-label="Previous week" onClick={() => setStart(addDays(start, -7))}><ChevronLeft className="size-4" aria-hidden /></Button>
          <Button variant="secondary" onClick={() => setStart(monday(new Date()))}>Today</Button>
          <Button variant="secondary" aria-label="Next week" onClick={() => setStart(addDays(start, 7))}><ChevronRight className="size-4" aria-hidden /></Button>
          <span className="text-sm font-medium" aria-live="polite">{days[0].toLocaleDateString("en-IN", { day: "numeric", month: "short" })} – {days[6].toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</span>
        </div>
      </div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest-900" checked={mine} onChange={(e) => setMine(e.target.checked)} />Only mine</label>
        <div className="w-56"><SelectInput label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All kinds</option>{kinds.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</SelectInput></div>
      </div>
      {q.isError ? <ErrorState message={errorMessage(q.error, "Couldn’t load the calendar.")} onRetry={() => void q.refetch()} /> : (
        <ol aria-label="Week" className="grid gap-2 md:grid-cols-7">
          {days.map((d) => { const list = byDay(d); const isToday = ist(d) === today; return (
            <li key={ist(d)} aria-label={d.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })} className={cx("min-h-24 rounded-xl bg-white p-2 ring-1", isToday ? "ring-2 ring-forest-700" : "ring-line", list.length === 0 && "max-md:hidden")}>
              <p className={cx("mb-2 text-xs font-semibold", isToday ? "text-forest-800" : "text-muted")}>{d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}{isToday ? " · Today" : ""}</p>
              {q.isPending ? <div className="h-12 animate-pulse rounded-lg bg-paper" /> : <div className="space-y-1.5">{list.map((i) => <Item key={i.id} i={i} />)}</div>}
            </li>); })}
        </ol>
      )}
      {q.data && items.length === 0 && <p className="mt-3 text-sm text-muted">Nothing scheduled this week{mine ? " for you" : ""}.</p>}
    </div>
  );
}
