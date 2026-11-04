import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye } from "lucide-react";
import { Alert, Button, Modal, TextArea, TextInput, cx } from "../ui";
import { api, errorMessage } from "../../lib/api";

interface Legal { developer_legal_name: string | null; rera_number: string | null; registered_address: string | null; signatory_name: string | null;
  signatory_designation: string | null; gstin: string | null; cin: string | null }
const LEGAL_KEYS: (keyof Legal)[] = ["developer_legal_name", "rera_number", "registered_address", "signatory_name", "signatory_designation", "gstin", "cin"];
interface Bank { bank_name: string | null; account_holder_name: string | null; account_number_masked: string | null; account_number: string | null; ifsc: string | null; branch: string | null }
export interface Readiness { ready: boolean; missing: string[]; legal_missing: string[]; bank_missing: string[]; schedule_ok: boolean; schedule_note: string }

export function useReadiness(projectId: number, enabled: boolean) {
  return useQuery({ queryKey: ["readiness", projectId], queryFn: async () => (await api.get<Readiness>(`/projects/${projectId}/doc-readiness`)).data, enabled });
}

/** Banner on the project page: what's missing before letters and demands can be generated. */
export function ReadinessBanner({ projectId, isAdmin, onOpen }: { projectId: number; isAdmin: boolean; onOpen: () => void }) {
  const r = useReadiness(projectId, true);
  if (!r.data || r.data.ready) return null;
  return (
    <div role="status" className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gold-300 bg-gold-100/60 px-4 py-3 text-sm">
      <span><b>{r.data.missing.length} {r.data.missing.length === 1 ? "detail" : "details"} missing</b> before documents can be generated: {r.data.missing.join(", ")}.</span>
      {isAdmin && <Button variant="secondary" onClick={onOpen}>Add legal &amp; bank details</Button>}
    </div>
  );
}

export function LegalBankDialog({ projectId, onClose }: { projectId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"legal" | "bank">("legal");
  const legal = useQuery({ queryKey: ["legal", projectId], queryFn: async () => (await api.get<Legal>(`/projects/${projectId}/legal`)).data });
  const bank = useQuery({ queryKey: ["bank", projectId], queryFn: async () => (await api.get<Bank>(`/projects/${projectId}/bank`)).data });
  const [l, setL] = useState<Record<keyof Legal, string> | null>(null);
  const [b, setB] = useState({ bank_name: "", account_holder_name: "", account_number: "", ifsc: "", branch: "" });
  const [revealed, setRevealed] = useState<string | null>(null);
  // Only the editable fields (the server refuses anything else, such as updated_at)
  useEffect(() => {
    if (legal.data && !l) setL(Object.fromEntries(LEGAL_KEYS.map((k) => [k, legal.data[k] ?? ""])) as Record<keyof Legal, string>);
  }, [legal.data, l]);
  useEffect(() => { if (bank.data) setB((x) => ({ ...x, bank_name: bank.data.bank_name ?? "", account_holder_name: bank.data.account_holder_name ?? "", ifsc: bank.data.ifsc ?? "", branch: bank.data.branch ?? "" })); }, [bank.data]);
  const done = () => { for (const k of [["legal"], ["bank"], ["readiness"], ["cost-sheet"]]) void qc.invalidateQueries({ queryKey: k }); };
  const saveLegal = useMutation({ mutationFn: async (body: Record<string, string | null>) => (await api.put(`/projects/${projectId}/legal`, body)).data, onSuccess: done });
  const saveBank = useMutation({ mutationFn: async (body: Record<string, string | null>) => (await api.put(`/projects/${projectId}/bank`, body)).data,
    onSuccess: () => { done(); setB((x) => ({ ...x, account_number: "" })); } });
  const reveal = useMutation({ mutationFn: async () => (await api.get<Bank>(`/projects/${projectId}/bank`, { params: { reveal: true } })).data, onSuccess: (d) => setRevealed(d.account_number) });
  const v = (x: string) => x.trim() || null;
  return (
    <Modal title="Legal & bank details" onClose={onClose}>
      <div role="tablist" aria-label="Details" className="mb-4 flex gap-1 rounded-lg bg-paper p-1">
        {(["legal", "bank"] as const).map((t) => <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
          className={cx("min-h-10 flex-1 rounded-md text-sm", tab === t ? "bg-forest-900 text-white" : "")}>{t === "legal" ? "Legal details" : "Bank details"}</button>)}
      </div>
      {tab === "legal" && l && (
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); saveLegal.mutate(Object.fromEntries(Object.entries(l).map(([k, x]) => [k, v(x)]))); }}>
          {saveLegal.isError && <Alert>{errorMessage(saveLegal.error)}</Alert>}
          {saveLegal.isSuccess && <p role="status" className="text-sm text-forest-800">Saved.</p>}
          <TextInput label="Developer’s legal name" value={l.developer_legal_name} onChange={(e) => setL({ ...l, developer_legal_name: e.target.value })} maxLength={200} />
          <TextInput label="RERA registration number" value={l.rera_number} onChange={(e) => setL({ ...l, rera_number: e.target.value })} maxLength={50} />
          <TextArea label="Registered address" value={l.registered_address} onChange={(e) => setL({ ...l, registered_address: e.target.value })} rows={2} />
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Signatory name" value={l.signatory_name} onChange={(e) => setL({ ...l, signatory_name: e.target.value })} maxLength={150} />
            <TextInput label="Signatory designation" value={l.signatory_designation} onChange={(e) => setL({ ...l, signatory_designation: e.target.value })} maxLength={100} />
            <TextInput label="GSTIN" value={l.gstin} onChange={(e) => setL({ ...l, gstin: e.target.value })} maxLength={20} hint="15 characters, e.g. 27AAPFU0939F1ZV" />
            <TextInput label="CIN (if a company)" value={l.cin} onChange={(e) => setL({ ...l, cin: e.target.value })} maxLength={21} />
          </div>
          <div className="flex justify-end"><Button type="submit" loading={saveLegal.isPending}>Save legal details</Button></div>
        </form>
      )}
      {tab === "bank" && (
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); saveBank.mutate({ bank_name: v(b.bank_name), account_holder_name: v(b.account_holder_name),
          ifsc: v(b.ifsc), branch: v(b.branch), ...(b.account_number.trim() ? { account_number: b.account_number.trim() } : {}) }); }}>
          {saveBank.isError && <Alert>{errorMessage(saveBank.error)}</Alert>}
          {saveBank.isSuccess && <p role="status" className="text-sm text-forest-800">Saved.</p>}
          <TextInput label="Bank name" value={b.bank_name} onChange={(e) => setB({ ...b, bank_name: e.target.value })} maxLength={150} />
          <TextInput label="Account holder name" value={b.account_holder_name} onChange={(e) => setB({ ...b, account_holder_name: e.target.value })} maxLength={200} />
          <TextInput label="Account number" inputMode="numeric" value={b.account_number} onChange={(e) => setB({ ...b, account_number: e.target.value })}
            placeholder={bank.data?.account_number_masked ? `Saved: ${bank.data.account_number_masked} (leave empty to keep)` : "9 to 18 digits"} autoComplete="off" />
          {bank.data?.account_number_masked && (
            <p className="text-sm">{revealed ? <>Full number: <b>{revealed}</b></> :
              <Button type="button" variant="ghost" loading={reveal.isPending} onClick={() => reveal.mutate()}><Eye className="size-4" aria-hidden />Show full number (logged)</Button>}</p>)}
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="IFSC code" value={b.ifsc} onChange={(e) => setB({ ...b, ifsc: e.target.value })} maxLength={11} placeholder="HDFC0001234" />
            <TextInput label="Branch" value={b.branch} onChange={(e) => setB({ ...b, branch: e.target.value })} maxLength={150} />
          </div>
          <p className="text-xs text-muted">The account number is stored encrypted and shown masked.</p>
          <div className="flex justify-end"><Button type="submit" loading={saveBank.isPending}>Save bank details</Button></div>
        </form>
      )}
    </Modal>
  );
}
