import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { MapPin, Plus } from "lucide-react";
import { ProjectFormDialog } from "../../components/inventory/InventoryDialogs";
import { Badge, Button, ErrorState, PageHeader } from "../../components/ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { useProjectList } from "../../hooks/useInventory";
import { errorMessage } from "../../lib/api";
import { PROJECT_STATUS_LABELS, PROJECT_TYPE_LABELS } from "../../lib/inventory";
import type { ProjectFull, UnitCounts } from "../../lib/inventory";

function Availability({ c }: { c: UnitCounts }) {
  if (!c.total) return <p className="text-sm text-muted">No units added yet</p>;
  const parts = [
    { n: c.available, cls: "bg-emerald-400", label: "available" },
    { n: c.on_hold, cls: "bg-amber-400", label: "on hold" },
    { n: c.booked, cls: "bg-gold-500", label: "booked" },
    { n: c.sold, cls: "bg-stone-400", label: "agreement done" },
  ];
  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded-full bg-paper" aria-hidden>
        {parts.map((p) => p.n > 0 && <span key={p.label} className={p.cls} style={{ width: `${(p.n / c.total) * 100}%` }} />)}
      </div>
      <p className="mt-1.5 text-sm"><b>{c.available}</b> of {c.total} available
        {c.on_hold ? <span className="text-muted"> · {c.on_hold} on hold</span> : null}
        {c.booked + c.sold ? <span className="text-muted"> · {c.booked + c.sold} booked or sold</span> : null}
      </p>
    </div>
  );
}

export function ProjectsPage() {
  const me = useCurrentUser();
  const isAdmin = me.role === "admin";
  const navigate = useNavigate();
  const [showInactive, setShowInactive] = useState(false);
  const projects = useProjectList(isAdmin && showInactive);
  const [adding, setAdding] = useState(false);

  return (
    <>
      <PageHeader title="Projects" description="Inventory across developer projects and resale listings."
        action={isAdmin ? <Button onClick={() => setAdding(true)}><Plus className="size-4" aria-hidden />New project</Button> : undefined} />
      {isAdmin && (
        <label className="mb-4 flex items-center gap-2 text-sm">
          <input type="checkbox" className="size-4 accent-forest-900" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          Show inactive projects
        </label>
      )}
      {projects.isPending && <div className="grid gap-3 sm:grid-cols-2">{[0, 1].map((i) => <div key={i} className="h-36 animate-pulse rounded-xl bg-white" />)}</div>}
      {projects.isError && <ErrorState message={errorMessage(projects.error, "Couldn’t load projects.")} onRetry={() => void projects.refetch()} />}
      {projects.isSuccess && projects.data.length === 0 && (
        <div className="rounded-xl border border-dashed border-line bg-white px-6 py-12 text-center">
          <p className="font-display text-xl text-forest-900">No projects yet</p>
          <p className="mt-1 text-sm text-muted">{isAdmin ? "Add your first project to start building its inventory." : "An admin will add projects here."}</p>
        </div>
      )}
      {projects.isSuccess && projects.data.length > 0 && (
        <ul className="grid gap-3 sm:grid-cols-2">
          {projects.data.map((p: ProjectFull) => (
            <li key={p.id}>
              <Link to={`/projects/${p.id}`} className="block h-full rounded-xl border border-line bg-white p-4 hover:border-forest-700">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <h2 className="font-display text-xl text-forest-900">{p.name}</h2>
                  <div className="flex gap-1.5">
                    {!p.is_active && <Badge tone="muted">Inactive</Badge>}
                    <Badge tone={p.project_type === "resale" ? "gold" : "neutral"}>{PROJECT_TYPE_LABELS[p.project_type]}</Badge>
                  </div>
                </div>
                <p className="text-sm text-muted">
                  {p.developer?.name ?? "Resale"} · {PROJECT_STATUS_LABELS[p.status]}
                </p>
                {p.location && <p className="mt-0.5 flex items-center gap-1 text-sm text-muted"><MapPin className="size-3.5" aria-hidden />{p.location}</p>}
                <div className="mt-3">{p.units && <Availability c={p.units} />}</div>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {adding && <ProjectFormDialog onClose={() => setAdding(false)} onSaved={(p) => navigate(`/projects/${p.id}`)} />}
    </>
  );
}
