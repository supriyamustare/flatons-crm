import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, Check, FileText, Plus, Trash2, X } from "lucide-react";
import { Alert, Badge, Button, ErrorState, Modal, PageHeader, SelectInput, TextArea, TextInput, cx } from "../../components/ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { DOC_LABELS, OWNERSHIP_LABELS, kycFileUrl, useCase, useCaseAction } from "../../hooks/usePostSales";
import type { CaseDetail, KycDocType, OwnershipType, Requirement } from "../../hooks/usePostSales";
import { errorMessage, formatDateTime } from "../../lib/api";
import { formatMobile, formatRupees } from "../../lib/leads";
import { statusBadge } from "./PostSalesPage";

type Tab = "handover" | "customer" | "kyc" | "history";
const ENTITY: OwnershipType[] = ["company", "partnership", "huf", "trust", "other"];
const HISTORY: Record<string, string> = {
  created: "Case created from the booking", accepted: "Handover accepted", returned_to_sales: "Returned to sales", resent_by_sales: "Resent by sales",
  assigned: "Owner assigned", profile_saved: "Customer details saved", approval_reopened: "Approval reopened", kyc_uploaded: "KYC document uploaded",
  kyc_verified: "KYC document verified", kyc_rejected: "KYC document rejected", onboarding_under_review: "Onboarding under review",
  onboarding_clarification_required: "Clarification requested", onboarding_approved: "Onboarding approved",
};

function ReasonDialog({ title, label, cta, onClose, onSubmit, busy, error }: { title: string; label: string; cta: string; onClose: () => void;
  onSubmit: (r: string) => void; busy: boolean; error: unknown }) {
  const [r, setR] = useState("");
  return (
    <Modal title={title} onClose={onClose}>
      <form className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); onSubmit(r.trim()); }}>
        {error ? <Alert>{errorMessage(error)}</Alert> : null}
        <TextArea label={label} value={r} onChange={(e) => setR(e.target.value)} rows={3} maxLength={500} autoFocus />
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={busy} disabled={r.trim().length < 3}>{cta}</Button></div>
      </form>
    </Modal>
  );
}

function Handover({ c, act }: { c: CaseDetail; act: ReturnType<typeof useCaseAction> }) {
  const me = useCurrentUser();
  const [returning, setReturning] = useState(false);
  const editor = ["admin", "crm_manager", "postsales_exec"].includes(me.role);
  const blocked = c.handover.filter((h) => h.required && !h.ok);
  return (
    <section role="tabpanel" aria-label="Handover" className="rounded-xl bg-white p-5 ring-1 ring-line">
      {c.status === "returned_to_sales" && <div className="mb-3"><Alert>Returned to sales: {c.returned_reason}</Alert></div>}
      <ul className="space-y-1.5 text-sm">
        {c.handover.map((h) => (
          <li key={h.item} className="flex items-center gap-2">
            {h.ok ? <Check className="size-4 text-forest-700" aria-hidden /> : <X className={cx("size-4", h.required ? "text-danger" : "text-gold-600")} aria-hidden />}
            <span>{h.item}</span>
            <span className="sr-only">{h.ok ? "present" : "missing"}</span>
            {!h.ok && <span className="text-xs text-muted">{h.required ? "(required)" : "(optional)"}</span>}
          </li>
        ))}
      </ul>
      {act.isError && <div className="mt-3"><Alert>{errorMessage(act.error)}</Alert></div>}
      {c.status === "handover_pending" && editor && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button loading={act.isPending} disabled={blocked.length > 0} onClick={() => act.mutate({ path: `/post-sales/cases/${c.id}/accept` })}>Accept handover</Button>
          <Button variant="secondary" onClick={() => setReturning(true)}>Return to sales</Button>
        </div>
      )}
      {c.status === "accepted" && <p className="mt-4 text-sm text-muted">Accepted {c.accepted_at ? formatDateTime(c.accepted_at) : ""}.</p>}
      {returning && <ReasonDialog title="Return to sales" label="What does sales need to fix?" cta="Return to sales" busy={act.isPending} error={act.error}
        onClose={() => setReturning(false)} onSubmit={(reason) => act.mutate({ path: `/post-sales/cases/${c.id}/return`, body: { reason } }, { onSuccess: () => setReturning(false) })} />}
    </section>
  );
}

type CoForm = { id?: number; name: string; relation: string; pan: string; mobile: string; email: string; ownership_pct: string; date_of_birth: string };

function Customer({ c, act }: { c: CaseDetail; act: ReturnType<typeof useCaseAction> }) {
  const p = c.profile;
  const [f, setF] = useState(() => ({
    ownership_type: (p?.ownership_type ?? "individual") as OwnershipType, legal_name: p?.legal_name ?? "", entity_name: p?.entity_name ?? "",
    date_of_birth: p?.date_of_birth ?? "", pan: p?.pan ?? "", ownership_pct: p?.ownership_pct ? String(Number(p.ownership_pct)) : "",
    mobile: p?.mobile ?? "", email: p?.email ?? "", correspondence_address: p?.correspondence_address ?? "", permanent_address: p?.permanent_address ?? "",
    preferred_language: p?.preferred_language ?? "", contact_email: p?.contact_email ?? true, contact_sms: p?.contact_sms ?? true, contact_whatsapp: p?.contact_whatsapp ?? false,
    consent_portal: Boolean(p?.consent_portal_at), consent_electronic: Boolean(p?.consent_electronic_at), consent_data: Boolean(p?.consent_data_at),
    nominee_name: p?.nominee_name ?? "", nominee_relation: p?.nominee_relation ?? "", nominee_mobile: p?.nominee_mobile ?? "",
  }));
  const [co, setCo] = useState<CoForm[]>(() => c.co_applicants.map((x) => ({ id: x.id, name: x.name, relation: x.relation ?? "", pan: x.pan ?? "", mobile: x.mobile ?? "",
    email: x.email ?? "", ownership_pct: x.ownership_pct ? String(Number(x.ownership_pct)) : "", date_of_birth: x.date_of_birth ?? "" })));
  const [saved, setSaved] = useState(false);
  const ro = !c.can_edit;
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const tick = (k: keyof typeof f) => (e: { target: { checked: boolean } }) => setF({ ...f, [k]: e.target.checked });
  const v = (x: string) => x.trim() || null;
  const entity = ENTITY.includes(f.ownership_type);
  const shares = [f.ownership_pct, ...co.map((x) => x.ownership_pct)].reduce((a, b) => a + (Number(b) || 0), 0);
  const submit = (e: FormEvent) => {
    e.preventDefault(); setSaved(false);
    act.mutate({ method: "put", path: `/post-sales/cases/${c.id}/profile`, body: {
      ...f, legal_name: v(f.legal_name), entity_name: entity ? v(f.entity_name) : null, date_of_birth: f.date_of_birth || null, pan: v(f.pan),
      ownership_pct: f.ownership_pct ? Number(f.ownership_pct) : null, mobile: v(f.mobile), email: v(f.email), correspondence_address: v(f.correspondence_address),
      permanent_address: v(f.permanent_address), preferred_language: v(f.preferred_language), nominee_name: v(f.nominee_name), nominee_relation: v(f.nominee_relation),
      nominee_mobile: v(f.nominee_mobile), communication_needs: null,
      co_applicants: f.ownership_type === "joint" ? co.map((x) => ({ id: x.id, name: x.name.trim(), relation: v(x.relation), pan: v(x.pan), mobile: v(x.mobile),
        email: v(x.email), ownership_pct: x.ownership_pct ? Number(x.ownership_pct) : null, date_of_birth: x.date_of_birth || null })) : [],
    } }, { onSuccess: () => setSaved(true) });
  };
  return (
    <section role="tabpanel" aria-label="Customer" className="rounded-xl bg-white p-5 ring-1 ring-line">
      {ro && c.status !== "accepted" && <div className="mb-3"><Alert>Accept the handover to edit customer details.</Alert></div>}
      <form className="space-y-5" onSubmit={submit}>
        <fieldset disabled={ro} className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <SelectInput label="Ownership" value={f.ownership_type} onChange={set("ownership_type")}>
              {(Object.keys(OWNERSHIP_LABELS) as OwnershipType[]).map((o) => <option key={o} value={o}>{OWNERSHIP_LABELS[o]}</option>)}
            </SelectInput>
            {entity && <TextInput label="Entity name" value={f.entity_name} onChange={set("entity_name")} maxLength={200} />}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <TextInput label={entity ? "Authorized signatory (legal name)" : "Legal name (as on PAN)"} value={f.legal_name} onChange={set("legal_name")} maxLength={200} />
            <TextInput label="PAN" value={f.pan} onChange={set("pan")} maxLength={10} placeholder="ABCDE1234F" />
            <TextInput label="Date of birth" type="date" value={f.date_of_birth} onChange={set("date_of_birth")} />
            <TextInput label="Mobile" type="tel" value={f.mobile} onChange={set("mobile")} maxLength={20} />
            <TextInput label="Email" type="email" value={f.email} onChange={set("email")} maxLength={254} />
            {f.ownership_type === "joint" && <TextInput label="Ownership share (%)" inputMode="decimal" value={f.ownership_pct} onChange={set("ownership_pct")} />}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <TextArea label="Correspondence address" value={f.correspondence_address} onChange={set("correspondence_address")} rows={2} />
            <TextArea label="Permanent address" value={f.permanent_address} onChange={set("permanent_address")} rows={2} />
          </div>
          {f.ownership_type === "joint" && (
            <fieldset className="rounded-lg bg-paper p-3">
              <legend className="text-sm font-semibold">Co-applicants <span className={cx("font-normal", shares === 100 ? "text-forest-800" : "text-danger")}>(shares total {shares}%)</span></legend>
              {co.map((x, i) => (
                <div key={i} className="mt-2 grid grid-cols-2 gap-2 border-b border-line pb-2 sm:grid-cols-4">
                  {(["name", "relation", "pan", "mobile", "email", "ownership_pct", "date_of_birth"] as (keyof CoForm)[]).map((k) => (
                    <TextInput key={k} label={`Co-applicant ${i + 1} ${{ name: "name", relation: "relation", pan: "PAN", mobile: "mobile", email: "email", ownership_pct: "share (%)", date_of_birth: "date of birth", id: "" }[k]}`}
                      type={k === "date_of_birth" ? "date" : "text"} value={String(x[k] ?? "")}
                      onChange={(e) => setCo(co.map((y, j) => (j === i ? { ...y, [k]: e.target.value } : y)))} />
                  ))}
                  <button type="button" aria-label={`Remove co-applicant ${x.name || i + 1}`} onClick={() => setCo(co.filter((_, j) => j !== i))}
                    className="grid size-10 place-items-center self-end rounded-lg text-muted hover:bg-danger-soft hover:text-danger"><Trash2 className="size-4" /></button>
                </div>
              ))}
              <Button type="button" variant="ghost" onClick={() => setCo([...co, { name: "", relation: "", pan: "", mobile: "", email: "", ownership_pct: "", date_of_birth: "" }])}>
                <Plus className="size-4" aria-hidden />Add co-applicant</Button>
            </fieldset>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <TextInput label="Nominee name" value={f.nominee_name} onChange={set("nominee_name")} maxLength={150} />
            <TextInput label="Nominee relation" value={f.nominee_relation} onChange={set("nominee_relation")} maxLength={60} />
            <TextInput label="Nominee mobile" type="tel" value={f.nominee_mobile} onChange={set("nominee_mobile")} maxLength={20} />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <fieldset className="space-y-1 text-sm"><legend className="mb-1 font-semibold">Communication</legend>
              <TextInput label="Preferred language" value={f.preferred_language} onChange={set("preferred_language")} maxLength={40} placeholder="e.g. Marathi" />
              {([["contact_email", "Contact by email"], ["contact_sms", "Contact by SMS"], ["contact_whatsapp", "Contact by WhatsApp"]] as const).map(([k, l]) => (
                <label key={k} className="flex min-h-9 items-center gap-2"><input type="checkbox" className="size-4 accent-forest-900" checked={f[k]} onChange={tick(k)} />{l}</label>))}
            </fieldset>
            <fieldset className="space-y-1 text-sm"><legend className="mb-1 font-semibold">Consents (time recorded when given)</legend>
              {([["consent_data", "Data processing", p?.consent_data_at], ["consent_electronic", "Electronic communications", p?.consent_electronic_at],
                ["consent_portal", "Customer portal access", p?.consent_portal_at]] as const).map(([k, l, at]) => (
                <label key={k} className="flex min-h-9 items-center gap-2"><input type="checkbox" className="size-4 accent-forest-900" checked={f[k]} onChange={tick(k)} />{l}
                  {at && <span className="text-xs text-muted">({formatDateTime(at)})</span>}</label>))}
            </fieldset>
          </div>
        </fieldset>
        {c.profile_problems.length > 0 && <p className="text-sm text-gold-600">Still needed before approval: {c.profile_problems.join(", ")}.</p>}
        {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
        {saved && !act.isError && <p role="status" className="text-sm text-forest-800">Saved.</p>}
        {!ro && <div className="flex justify-end"><Button type="submit" loading={act.isPending}>Save customer details</Button></div>}
      </form>
    </section>
  );
}

function Kyc({ c, act }: { c: CaseDetail; act: ReturnType<typeof useCaseAction> }) {
  const me = useCurrentUser();
  const [uploading, setUploading] = useState<Requirement | null>(null);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [clarify, setClarify] = useState(false);
  const docsById = new Map(c.documents.map((d) => [d.id, d]));
  const tone = (s: string) => (s === "verified" ? "neutral" : s === "rejected" || s === "missing" ? "gold" : "muted") as "neutral" | "gold" | "muted";
  const groups = Array.from(new Set(c.requirements.map((r) => r.applicant)));
  return (
    <section role="tabpanel" aria-label="KYC" className="space-y-4">
      {c.onboarding_status === "clarification_required" && <Alert>Clarification required: {c.clarification_reason}</Alert>}
      {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
      {groups.map((who) => (
        <div key={who} className="rounded-xl bg-white p-4 ring-1 ring-line">
          <h3 className="mb-2 font-semibold">{who}</h3>
          <ul className="divide-y divide-line">
            {c.requirements.filter((r) => r.applicant === who).map((r) => {
              const doc = r.document_id ? docsById.get(r.document_id) : undefined;
              const mineUpload = doc?.uploaded_by_id === me.id && me.role !== "admin";
              return (
                <li key={`${r.applicant_id}-${r.key}`} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                  <div className="min-w-0"><p className="font-medium">{r.label}</p>
                    {doc && <p className="text-xs text-muted">{DOC_LABELS[doc.doc_type]} · {doc.file_name} · uploaded {formatDateTime(doc.uploaded_at)}{doc.review_note ? ` · Rejected: ${doc.review_note}` : ""}</p>}</div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={tone(r.status)}>{r.status === "missing" ? "Missing" : r.status[0].toUpperCase() + r.status.slice(1)}</Badge>
                    {doc && c.can_view_kyc && <a href={kycFileUrl(doc.id)} target="_blank" rel="noopener" className="inline-flex min-h-9 items-center gap-1 rounded-lg px-2 text-forest-800 underline"><FileText className="size-4" aria-hidden />View</a>}
                    {c.can_edit && doc?.status === "pending" && !mineUpload && <>
                      <Button variant="secondary" onClick={() => act.mutate({ path: `/post-sales/kyc/${doc.id}/verify` })}>Verify</Button>
                      <Button variant="ghost" onClick={() => setRejecting(doc.id)}>Reject</Button></>}
                    {c.can_edit && doc?.status === "pending" && mineUpload && <span className="text-xs text-muted">Another person must review</span>}
                    {c.can_edit && r.status !== "verified" && <Button variant="ghost" onClick={() => setUploading(r)}>{doc ? "Replace" : "Upload"}</Button>}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      {c.can_edit && (
        <div className="flex flex-wrap gap-2">
          {(c.onboarding_status === "documents_pending" || c.onboarding_status === "clarification_required") &&
            <Button variant="secondary" loading={act.isPending} onClick={() => act.mutate({ path: `/post-sales/cases/${c.id}/onboarding`, body: { action: "submit_for_review" } })}>Submit for review</Button>}
          {c.onboarding_status === "under_review" && <>
            <Button loading={act.isPending} onClick={() => act.mutate({ path: `/post-sales/cases/${c.id}/onboarding`, body: { action: "approve" } })}>Approve onboarding</Button>
            <Button variant="secondary" onClick={() => setClarify(true)}>Request clarification</Button></>}
        </div>
      )}
      {uploading && <UploadKyc c={c} req={uploading} onClose={() => setUploading(null)} />}
      {rejecting && <ReasonDialog title="Reject document" label="Why is it rejected?" cta="Reject" busy={act.isPending} error={act.error} onClose={() => setRejecting(null)}
        onSubmit={(reason) => act.mutate({ path: `/post-sales/kyc/${rejecting}/reject`, body: { reason } }, { onSuccess: () => setRejecting(null) })} />}
      {clarify && <ReasonDialog title="Request clarification" label="What needs clarifying?" cta="Request clarification" busy={act.isPending} error={act.error} onClose={() => setClarify(false)}
        onSubmit={(reason) => act.mutate({ path: `/post-sales/cases/${c.id}/onboarding`, body: { action: "request_clarification", reason } }, { onSuccess: () => setClarify(false) })} />}
    </section>
  );
}

function UploadKyc({ c, req, onClose }: { c: CaseDetail; req: Requirement; onClose: () => void }) {
  const act = useCaseAction(c.id);
  const [type, setType] = useState<KycDocType>(req.accepted_types[0]);
  const [file, setFile] = useState<File | null>(null);
  const [expiry, setExpiry] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("doc_type", type); form.append("file", file);
    if (req.applicant_id) form.append("co_applicant_id", String(req.applicant_id));
    if (expiry) form.append("expiry_date", expiry);
    act.mutate({ path: `/post-sales/cases/${c.id}/kyc`, body: form }, { onSuccess: onClose });
  };
  return (
    <Modal title={`Upload: ${req.label}`} onClose={onClose}>
      <form className="space-y-4" onSubmit={submit}>
        {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
        <p className="text-sm">For <b>{req.applicant}</b></p>
        {req.accepted_types.length > 1 && <SelectInput label="Document" value={type} onChange={(e) => setType(e.target.value as KycDocType)}>
          {req.accepted_types.map((t) => <option key={t} value={t}>{DOC_LABELS[t]}</option>)}</SelectInput>}
        <div className="space-y-1.5"><label htmlFor="kyc-file" className="block text-sm font-medium">File</label>
          <input id="kyc-file" type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm file:mr-3 file:min-h-10 file:rounded-lg file:border-0 file:bg-forest-50 file:px-3" />
          <p className="text-xs text-muted">PDF, JPG or PNG, up to 10 MB.</p></div>
        {["passport", "driving_licence"].includes(type) && <TextInput label="Expiry date" type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} />}
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={act.isPending} disabled={!file}>Upload</Button></div>
      </form>
    </Modal>
  );
}

export function CasePage() {
  const id = Number(useParams().caseId);
  const me = useCurrentUser();
  const q = useCase(id);
  const act = useCaseAction(id);
  const [tab, setTab] = useState<Tab>("handover");
  useEffect(() => { if (q.data && q.data.status === "accepted" && tab === "handover") setTab("customer"); }, [q.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  if (q.isPending) return <div className="h-64 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <ErrorState message={errorMessage(q.error, "Couldn’t load this case.")} onRetry={() => void q.refetch()} />;
  const c = q.data;
  return (
    <>
      <Link to="/post-sales" className="mb-3 inline-flex items-center gap-1 text-sm text-forest-800 hover:underline"><ArrowLeft className="size-4" aria-hidden />All cases</Link>
      <PageHeader title={`${c.case_code}: ${c.customer}`} description={`${c.project} · Unit ${c.unit_no} · ${formatRupees(c.agreed_price)} · booked ${c.booking_date}`} />
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        {statusBadge(c)}
        <span className="text-muted">Owner: {c.owner?.full_name ?? "Unassigned"}</span>
        <span className="text-muted">Sales: {c.sales_exec?.full_name ?? "—"}</span>
        {c.profile?.mobile && <a href={`tel:${c.profile.mobile}`} className="text-forest-800 underline">{formatMobile(c.profile.mobile)}</a>}
        {["admin", "crm_manager", "manager"].includes(me.role) && <Link to={`/bookings/${c.booking_id}`} className="text-forest-800 underline">{c.booking_code}</Link>}
        {c.kyc_total > 0 && <span className="text-muted">KYC {c.kyc_done}/{c.kyc_total} verified</span>}
      </div>
      <div role="tablist" aria-label="Case" className="mb-4 flex gap-1 overflow-x-auto rounded-xl bg-white p-1 ring-1 ring-line">
        {([["handover", "Handover"], ["customer", "Customer"], ["kyc", "KYC"], ["history", "History"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={cx("min-h-11 flex-1 rounded-lg px-3 text-sm whitespace-nowrap", tab === k ? "bg-forest-900 text-white" : "hover:bg-forest-50")}>{l}</button>
        ))}
      </div>
      {tab === "handover" && <Handover c={c} act={act} />}
      {tab === "customer" && <Customer key={c.profile?.legal_name ?? ""} c={c} act={act} />}
      {tab === "kyc" && <Kyc c={c} act={act} />}
      {tab === "history" && (
        <section role="tabpanel" aria-label="History" className="rounded-xl bg-white p-5 ring-1 ring-line">
          <ol className="space-y-2 text-sm">{c.history.map((h, i) => (
            <li key={i}><b>{HISTORY[h.action] ?? h.action}</b>{h.details?.reason ? `: ${String(h.details.reason)}` : ""}
              <span className="block text-xs text-muted">{h.actor?.full_name ?? "System"}, {formatDateTime(h.at)}</span></li>))}</ol>
        </section>
      )}
    </>
  );
}
