import { useState } from "react";
import type { FormEvent } from "react";
import { FileText, Plus, Trash2 } from "lucide-react";
import { Alert, Badge, Button, ErrorState, Modal, PageHeader, SelectInput, TextArea, TextInput, cx } from "../components/ui";
import { useProjects } from "../hooks/useLeads";
import { receiptUrl, useCampaigns, useCreateExpense, useDeleteExpense, useExpenses, useSaveCampaign } from "../hooks/useMarketing";
import { useReport } from "../hooks/useReports";
import { errorMessage } from "../lib/api";
import { formatRupees } from "../lib/leads";
import { CATEGORIES, CATEGORY_LABELS, CHANNELS, CHANNEL_LABELS, RECEIPT_MAX_BYTES, RECEIPT_TYPES, campaignIsActive } from "../lib/marketing";
import type { Campaign, Channel, ExpenseCategory } from "../lib/marketing";

const today = () => new Date().toISOString().slice(0, 10);
const money = (v: number | null) => (v === null ? "N/A" : formatRupees(v));

function CampaignDialog({ campaign, onClose }: { campaign?: Campaign; onClose: () => void }) {
  const save = useSaveCampaign();
  const projects = useProjects();
  const [name, setName] = useState(campaign?.name ?? "");
  const [channel, setChannel] = useState<Channel>(campaign?.channel ?? "google_ads");
  const [projectId, setProjectId] = useState(campaign?.project ? String(campaign.project.id) : "");
  const [start, setStart] = useState(campaign?.start_date ?? today());
  const [end, setEnd] = useState(campaign?.end_date ?? "");
  const [description, setDescription] = useState(campaign?.description ?? "");
  const datesOk = !end || end >= start;
  return (
    <Modal title={campaign ? `Edit ${campaign.name}` : "New campaign"} onClose={onClose}>
      <form className="space-y-4" noValidate onSubmit={(e: FormEvent) => {
        e.preventDefault();
        save.mutate({ id: campaign?.id, name: name.trim(), channel, project_id: projectId ? Number(projectId) : null,
          start_date: start, end_date: end || null, description: description.trim() || null }, { onSuccess: onClose });
      }}>
        {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
        <TextInput label="Campaign name" value={name} onChange={(e) => setName(e.target.value)} autoFocus maxLength={150} placeholder="e.g. Google Ads: Green Meadows Diwali" />
        <SelectInput label="Channel" value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
          {CHANNELS.map((c) => <option key={c} value={c}>{CHANNEL_LABELS[c]}</option>)}
        </SelectInput>
        <SelectInput label="Project (optional)" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">All projects / general</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </SelectInput>
        <div className="grid grid-cols-2 gap-3">
          <TextInput label="Starts" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          <TextInput label="Ends (optional)" type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} />
        </div>
        {!datesOk && <p className="text-sm text-danger">The end date can’t be before the start date.</p>}
        <TextArea label="Notes (optional)" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={5000} />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!name.trim() || !start || !datesOk}>{campaign ? "Save" : "Create campaign"}</Button>
        </div>
      </form>
    </Modal>
  );
}

function ExpenseDialog({ campaigns, onClose, defaultCampaign }: { campaigns: Campaign[]; onClose: () => void; defaultCampaign?: number }) {
  const create = useCreateExpense();
  const [campaignId, setCampaignId] = useState(defaultCampaign ? String(defaultCampaign) : "");
  const [spentOn, setSpentOn] = useState(today());
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState<ExpenseCategory>("ad_spend");
  const [vendor, setVendor] = useState("");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const rupees = Math.round(Number(amount));
  const amountOk = amount.trim() !== "" && Number.isFinite(rupees) && rupees > 0;

  return (
    <Modal title="Add expense" onClose={onClose}>
      <form className="space-y-4" noValidate onSubmit={(e: FormEvent) => {
        e.preventDefault();
        create.mutate({ campaign_id: Number(campaignId), spent_on: spentOn, amount: rupees, category,
          vendor: vendor.trim() || undefined, notes: notes.trim() || undefined, receipt: file }, { onSuccess: onClose });
      }}>
        {create.isError && <Alert>{errorMessage(create.error)}</Alert>}
        <SelectInput label="Campaign" value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
          <option value="" disabled>Choose a campaign</option>
          {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </SelectInput>
        <div className="grid grid-cols-2 gap-3">
          <TextInput label="Amount (₹)" type="number" inputMode="numeric" min={1} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="e.g. 45000" />
          <TextInput label="Date" type="date" value={spentOn} max={today()} onChange={(e) => setSpentOn(e.target.value)} />
        </div>
        <SelectInput label="Category" value={category} onChange={(e) => setCategory(e.target.value as ExpenseCategory)}>
          {CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
        </SelectInput>
        <TextInput label="Vendor (optional)" value={vendor} onChange={(e) => setVendor(e.target.value)} maxLength={150} placeholder="e.g. Google, Times Outdoor" />
        <TextInput label="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500} />
        <div className="space-y-1.5">
          <label htmlFor="receipt" className="block text-sm font-medium">Receipt (optional)</label>
          <input id="receipt" type="file" accept={RECEIPT_TYPES} className="block w-full text-sm file:mr-3 file:min-h-10 file:rounded-lg file:border-0 file:bg-forest-50 file:px-3 file:text-forest-900"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFileError(f && f.size > RECEIPT_MAX_BYTES ? "Receipts can be at most 10 MB" : null);
              setFile(f && f.size <= RECEIPT_MAX_BYTES ? f : null);
            }} />
          <p className="text-xs text-muted">PDF, JPG or PNG, up to 10 MB.</p>
          {fileError && <p className="text-sm text-danger">{fileError}</p>}
        </div>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending} disabled={!campaignId || !amountOk || !spentOn}>Save expense</Button>
        </div>
      </form>
    </Modal>
  );
}

function CampaignsTab() {
  const campaigns = useCampaigns();
  const perf = useReport("campaigns", { range: "30d" });
  const [editing, setEditing] = useState<Campaign | "new" | null>(null);
  const byId = new Map(perf.data?.rows.map((r) => [r.campaign_id, r]) ?? []);
  return (
    <>
      <div className="mb-4 flex justify-end"><Button onClick={() => setEditing("new")}><Plus className="size-4" aria-hidden />New campaign</Button></div>
      {campaigns.isError && <ErrorState message={errorMessage(campaigns.error)} onRetry={() => void campaigns.refetch()} />}
      {campaigns.isSuccess && campaigns.data.length === 0 && (
        <p className="rounded-xl border border-dashed border-line bg-white px-6 py-10 text-center text-muted">No campaigns yet. Create one to start tracking spend and cost per lead.</p>
      )}
      {campaigns.isSuccess && campaigns.data.length > 0 && (
        <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-line">
          <table className="w-full min-w-[640px] text-sm">
            <caption className="px-4 pt-3 text-left text-xs text-muted">Spend, leads and cost per lead over the last 30 days</caption>
            <thead className="text-left text-xs text-muted"><tr>
              <th className="px-4 py-2 font-normal">Campaign</th><th className="px-2 py-2 text-right font-normal">Spend</th>
              <th className="px-2 py-2 text-right font-normal">Leads</th><th className="px-2 py-2 text-right font-normal">Cost per lead</th>
              <th className="px-4 py-2"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{campaigns.data.map((c) => {
              const r = byId.get(c.id);
              return (
                <tr key={c.id} className="border-t border-line">
                  <td className="px-4 py-3">
                    <span className="font-medium">{c.name}</span>{" "}
                    {campaignIsActive(c) ? <Badge>Running</Badge> : <Badge tone="muted">Not running</Badge>}
                    <span className="block text-xs text-muted">{CHANNEL_LABELS[c.channel]}{c.project ? ` · ${c.project.name}` : ""} · from {c.start_date}{c.end_date ? ` to ${c.end_date}` : ""}</span>
                  </td>
                  <td className="px-2 py-3 text-right tabular-nums">{formatRupees(r?.spend ?? 0)}</td>
                  <td className="px-2 py-3 text-right tabular-nums">{r?.leads ?? 0}</td>
                  <td className="px-2 py-3 text-right tabular-nums">{money(r ? r.cost_per_lead : null)}</td>
                  <td className="px-4 py-3 text-right"><Button variant="ghost" onClick={() => setEditing(c)}>Edit</Button></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      )}
      {editing && <CampaignDialog campaign={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function ExpensesTab() {
  const campaigns = useCampaigns();
  const [campaignId, setCampaignId] = useState("");
  const [channel, setChannel] = useState<Channel | "">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const [confirm, setConfirm] = useState<number | null>(null);
  const del = useDeleteExpense();
  const expenses = useExpenses({ campaign_id: campaignId ? Number(campaignId) : undefined, channel: channel || undefined,
    date_from: from || undefined, date_to: to || undefined, page });
  const d = expenses.data;
  return (
    <>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-full sm:w-64"><SelectInput label="Campaign" value={campaignId} onChange={(e) => { setCampaignId(e.target.value); setPage(1); }}>
          <option value="">All campaigns</option>{campaigns.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </SelectInput></div>
        <div className="w-full sm:w-48"><SelectInput label="Channel" value={channel} onChange={(e) => { setChannel(e.target.value as Channel | ""); setPage(1); }}>
          <option value="">All channels</option>{CHANNELS.map((c) => <option key={c} value={c}>{CHANNEL_LABELS[c]}</option>)}
        </SelectInput></div>
        <div className="w-[calc(50%-0.375rem)] sm:w-40"><TextInput label="From" type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }} /></div>
        <div className="w-[calc(50%-0.375rem)] sm:w-40"><TextInput label="To" type="date" value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} /></div>
        <Button className="ml-auto" onClick={() => setAdding(true)} disabled={!campaigns.data?.length}><Plus className="size-4" aria-hidden />Add expense</Button>
      </div>
      {!campaigns.data?.length && campaigns.isSuccess && <p className="mb-4 text-sm text-muted">Create a campaign first; every expense belongs to one.</p>}
      {d && (
        <section aria-label="Expense totals" className="mb-4 rounded-xl bg-white p-4 ring-1 ring-line">
          <p className="text-sm text-muted">Total for these filters</p>
          <p className="font-display text-2xl text-forest-900">{formatRupees(d.total_amount)}</p>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {Object.entries(d.by_channel).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0)).map(([ch, amt]) => (
              <li key={ch}><span className="text-muted">{CHANNEL_LABELS[ch as Channel]}</span> {formatRupees(amt ?? 0)}</li>
            ))}
          </ul>
        </section>
      )}
      {expenses.isError && <ErrorState message={errorMessage(expenses.error)} onRetry={() => void expenses.refetch()} />}
      {d && d.total === 0 && <p className="rounded-xl border border-dashed border-line bg-white px-6 py-10 text-center text-muted">No expenses match these filters.</p>}
      {d && d.total > 0 && (
        <ul className={cx("divide-y divide-line rounded-xl bg-white ring-1 ring-line", expenses.isPlaceholderData && "opacity-60")}>
          {d.items.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <p className="font-medium">{formatRupees(e.amount)} <span className="font-normal text-muted">· {CATEGORY_LABELS[e.category]}</span></p>
                <p className="text-sm text-muted">{e.campaign.name} · {e.spent_on}{e.vendor ? ` · ${e.vendor}` : ""}</p>
                {e.notes && <p className="text-sm">{e.notes}</p>}
              </div>
              <div className="flex items-center gap-1">
                {e.has_receipt && (
                  <a href={receiptUrl(e.id)} target="_blank" rel="noopener" className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-3 text-sm text-forest-800 hover:bg-forest-50">
                    <FileText className="size-4" aria-hidden />Receipt<span className="sr-only"> for {formatRupees(e.amount)} on {e.spent_on}</span>
                  </a>
                )}
                {confirm === e.id ? (
                  <>
                    <Button variant="danger" loading={del.isPending} onClick={() => del.mutate(e.id, { onSuccess: () => setConfirm(null) })}>Delete</Button>
                    <Button variant="secondary" onClick={() => setConfirm(null)}>Keep</Button>
                  </>
                ) : (
                  <button type="button" onClick={() => setConfirm(e.id)} aria-label={`Delete expense of ${formatRupees(e.amount)} on ${e.spent_on}`}
                    className="grid size-10 place-items-center rounded-lg text-muted hover:bg-danger-soft hover:text-danger"><Trash2 className="size-4" /></button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {d && d.total > d.page_size && (
        <div className="mt-4 flex items-center justify-between text-sm text-muted">
          <span>{(page - 1) * d.page_size + 1}–{Math.min(page * d.page_size, d.total)} of {d.total}</span>
          <div className="flex gap-2"><Button variant="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <Button variant="secondary" disabled={page * d.page_size >= d.total} onClick={() => setPage(page + 1)}>Next</Button></div>
        </div>
      )}
      {adding && campaigns.data && <ExpenseDialog campaigns={campaigns.data} defaultCampaign={campaignId ? Number(campaignId) : undefined} onClose={() => setAdding(false)} />}
    </>
  );
}

export function MarketingPage() {
  const [tab, setTab] = useState<"campaigns" | "expenses">("campaigns");
  return (
    <>
      <PageHeader title="Marketing" description="Campaigns, what they cost, and the leads they bring in." />
      <div role="tablist" aria-label="Marketing" className="mb-5 flex gap-1 rounded-xl bg-white p-1 ring-1 ring-line sm:max-w-sm">
        {(["campaigns", "expenses"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={cx("min-h-11 flex-1 rounded-lg text-sm", tab === t ? "bg-forest-900 text-white" : "hover:bg-forest-50")}>
            {t === "campaigns" ? "Campaigns" : "Expenses"}
          </button>
        ))}
      </div>
      {tab === "campaigns" ? <CampaignsTab /> : <ExpensesTab />}
    </>
  );
}
