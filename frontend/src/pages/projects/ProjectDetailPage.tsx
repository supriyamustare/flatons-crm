import { ProjectCostSheetDialog } from "../../components/inventory/ProjectCostSheetDialog";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, Building2, FileSpreadsheet, Pencil, Plus, Rows3 } from "lucide-react";
import { BuildingGrid, StatusLegend } from "../../components/inventory/BuildingGrid";
import { BuildingDialog, GenerateDialog, ProjectFormDialog, UnitFormDialog } from "../../components/inventory/InventoryDialogs";
import { UnitPanel } from "../../components/inventory/UnitPanel";
import { Badge, Button, ErrorState, Spinner, cx } from "../../components/ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { useInventory } from "../../hooks/useInventory";
import { errorMessage } from "../../lib/api";
import { PROJECT_STATUS_LABELS, PROJECT_TYPE_LABELS, UNIT_STATUS_LABELS, UNIT_TYPE_LABELS, floorLabel, formatArea } from "../../lib/inventory";
import type { Unit, UnitStatus } from "../../lib/inventory";
import { formatRupees } from "../../lib/leads";

type Dialog = { kind: "project" } | { kind: "building" } | { kind: "generate" } | { kind: "add-unit" } | { kind: "edit-unit"; unit: Unit };

export function ProjectDetailPage() {
  const { id } = useParams();
  const projectId = Number(id);
  const me = useCurrentUser();
  const isAdmin = me.role === "admin";
  const inv = useInventory(projectId);
  const [tab, setTab] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [costSettings, setCostSettings] = useState(false);

  const data = inv.data;
  const buildings = data?.buildings ?? [];
  const building = buildings.find((b) => b.id === tab) ?? buildings[0];
  useEffect(() => {
    if (buildings.length && !buildings.some((b) => b.id === tab)) setTab(buildings[0].id);
  }, [buildings, tab]);

  // Keep the side panel in sync with fresh data (e.g. after a hold or a refresh)
  const allUnits = useMemo(() => [...buildings.flatMap((b) => b.floors.flatMap((f) => f.units)), ...(data?.listings ?? [])], [buildings, data]);
  const selected = allUnits.find((u) => u.id === selectedId) ?? null;

  if (inv.isPending) return <Spinner label="Loading inventory" />;
  if (inv.isError) return <ErrorState message={errorMessage(inv.error, "Couldn’t load this project.")} onRetry={() => void inv.refetch()} />;
  const p = data!.project;
  const resale = p.project_type === "resale";
  const counts = data!.counts as unknown as Record<UnitStatus, number>;

  return (
    <div className={cx(selected && "md:pr-96")}>
      <Link to="/projects" className="mb-3 inline-flex items-center gap-1.5 text-sm text-forest-800"><ArrowLeft className="size-4" aria-hidden />All projects</Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl text-forest-900">{p.name}</h1>
          <p className="mt-1 text-sm text-muted">
            {p.developer?.name ?? "Resale"} · {PROJECT_STATUS_LABELS[p.status]}{p.location ? ` · ${p.location}` : ""}
          </p>
          <div className="mt-2 flex gap-1.5">
            <Badge tone={resale ? "gold" : "neutral"}>{PROJECT_TYPE_LABELS[p.project_type]}</Badge>
            {!p.is_active && <Badge tone="muted">Inactive</Badge>}
          </div>
        </div>
        {isAdmin && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setDialog({ kind: "project" })}><Pencil className="size-4" aria-hidden />Edit</Button>
            <Button variant="secondary" onClick={() => setCostSettings(true)}><FileSpreadsheet className="size-4" aria-hidden />Cost sheet settings</Button>
            {resale
              ? <Button onClick={() => setDialog({ kind: "add-unit" })}><Plus className="size-4" aria-hidden />Add listing</Button>
              : <Button onClick={() => setDialog({ kind: "building" })}><Building2 className="size-4" aria-hidden />Add building</Button>}
          </div>
        )}
      </div>
      {p.description && <p className="mb-5 max-w-3xl text-sm whitespace-pre-wrap">{p.description}</p>}

      <div className="sticky top-14 z-20 -mx-4 mb-4 bg-paper/95 px-4 py-2 backdrop-blur md:top-0">
        <StatusLegend counts={counts} />
      </div>

      {!resale && buildings.length === 0 && (
        <div className="rounded-xl border border-dashed border-line bg-white px-6 py-12 text-center">
          <p className="font-display text-xl text-forest-900">No buildings yet</p>
          <p className="mt-1 text-sm text-muted">{isAdmin ? "Add a building, then generate its floors and units in one go." : "An admin will add the buildings and units."}</p>
        </div>
      )}

      {!resale && building && (
        <>
          {buildings.length > 1 && (
            <div role="tablist" aria-label="Buildings" className="mb-3 flex gap-1 overflow-x-auto">
              {buildings.map((b) => (
                <button key={b.id} role="tab" aria-selected={b.id === building.id} onClick={() => setTab(b.id)}
                  className={cx("min-h-10 shrink-0 rounded-lg px-3 text-sm ring-1", b.id === building.id ? "bg-forest-900 text-white ring-forest-900" : "bg-white ring-line")}>
                  {b.name} <span className="opacity-70">{b.counts.available}/{b.counts.total}</span>
                </button>
              ))}
            </div>
          )}
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold">{building.name}</h2>
            {isAdmin && (
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => setDialog({ kind: "generate" })}><Rows3 className="size-4" aria-hidden />Add floors and units</Button>
                {building.floors.length > 0 && <Button variant="ghost" onClick={() => setDialog({ kind: "add-unit" })}><Plus className="size-4" aria-hidden />One unit</Button>}
              </div>
            )}
          </div>
          <BuildingGrid building={building} selectedId={selectedId} onSelect={(u) => setSelectedId(u.id)} />
        </>
      )}

      {resale && (
        data!.listings.length === 0 ? (
          <div className="rounded-xl border border-dashed border-line bg-white px-6 py-12 text-center">
            <p className="font-display text-xl text-forest-900">No listings yet</p>
          </div>
        ) : (
          <ul className="divide-y divide-line rounded-xl border border-line bg-white">
            {data!.listings.map((u) => (
              <li key={u.id}>
                <button type="button" onClick={() => setSelectedId(u.id)} aria-pressed={selectedId === u.id}
                  className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left hover:bg-paper">
                  <span>
                    <span className="font-medium">{u.unit_no}</span> · {UNIT_TYPE_LABELS[u.unit_type]} · {formatArea(u.carpet_sqft)}
                    {u.address_note && <span className="block text-sm text-muted">{u.address_note}</span>}
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="font-medium">{formatRupees(u.current_asking_price)}</span>
                    <Badge tone={u.status === "available" ? "neutral" : u.status === "on_hold" ? "gold" : "muted"}>{UNIT_STATUS_LABELS[u.status]}</Badge>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )
      )}

      {selected && <UnitPanel unit={selected} onClose={() => setSelectedId(null)} onEdit={() => setDialog({ kind: "edit-unit", unit: selected })} />}

      {dialog?.kind === "project" && <ProjectFormDialog project={p} onClose={() => setDialog(null)} />}
      {dialog?.kind === "building" && <BuildingDialog projectId={p.id} onClose={() => setDialog(null)} onCreated={(bid) => setTab(bid)} />}
      {dialog?.kind === "generate" && building && <GenerateDialog building={building} onClose={() => setDialog(null)} />}
      {dialog?.kind === "add-unit" && (
        <UnitFormDialog projectId={p.id} onClose={() => setDialog(null)}
          floors={resale ? undefined : building?.floors.map((f) => ({ id: f.id, label: floorLabel(f.number) }))} />
      )}
      {dialog?.kind === "edit-unit" && (
        <UnitFormDialog projectId={p.id} unit={dialog.unit} onClose={() => setDialog(null)} floors={resale ? undefined : []} />
      )}
      {costSettings && <ProjectCostSheetDialog projectId={p.id} onClose={() => setCostSettings(false)} />}
    </div>
  );
}
