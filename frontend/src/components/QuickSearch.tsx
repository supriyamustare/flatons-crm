import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { Plus, Search } from "lucide-react";

/** Header search: name, phone or lead ID. Opens Leads with the search filled in. Ctrl/⌘+K focuses it.
 *  The query travels in navigation state, never the address bar (phone numbers stay out of logs). */
export function QuickSearch() {
  const [q, setQ] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  function submit(e: FormEvent) {
    e.preventDefault();
    const term = q.trim();
    if (!term) return;
    navigate("/leads", { state: { quickSearch: term } });
    setQ("");
    ref.current?.blur();
  }
  return (
    <div className="mb-6 hidden items-center gap-3 md:flex">
      <form role="search" onSubmit={submit} className="relative max-w-md flex-1">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <label htmlFor="quick-search" className="sr-only">Search leads by name, mobile or lead ID</label>
        <input id="quick-search" ref={ref} value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off"
          placeholder="Search leads by name, mobile or lead ID"
          className="min-h-11 w-full rounded-lg border border-line bg-white pr-16 pl-9 text-sm" />
        <kbd className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 rounded border border-line px-1.5 text-xs text-muted">Ctrl K</kbd>
      </form>
      <Link to="/leads/new" className="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white hover:bg-forest-800">
        <Plus className="size-4" aria-hidden />Add lead
      </Link>
    </div>
  );
}
