import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { DuplicateBanner } from "../../components/leads/LeadBits";
import { Alert, Button, ErrorState, PageHeader, SelectInput, Spinner, TextArea, TextInput } from "../../components/ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { checkDuplicates, useAssignableUsers, useCreateLead, useLead, useProjects, useUpdateLead } from "../../hooks/useLeads";
import type { LeadPayload } from "../../hooks/useLeads";
import { errorMessage } from "../../lib/api";
import {
  CONFIG_LABELS, PURPOSE_LABELS, SOURCE_LABELS, SOURCES, TIMELINE_LABELS, lakhToRupees, rupeesToLakh,
} from "../../lib/leads";
import type { Duplicate, LeadDetail } from "../../lib/leads";

interface FormState {
  name: string; mobile: string; alt_mobile: string; email: string; city: string;
  source: string; sub_source: string; project_id: string; configuration: string;
  budget_min: string; budget_max: string; purpose: string; timeline: string;
  estimated_value: string; remarks: string; assigned_to_id: string;
}

const EMPTY: FormState = {
  name: "", mobile: "", alt_mobile: "", email: "", city: "", source: "", sub_source: "",
  project_id: "", configuration: "", budget_min: "", budget_max: "", purpose: "", timeline: "",
  estimated_value: "", remarks: "", assigned_to_id: "",
};

function fromLead(l: LeadDetail): FormState {
  return {
    name: l.name, mobile: l.mobile, alt_mobile: l.alt_mobile ?? "", email: l.email ?? "", city: l.city ?? "",
    source: l.source, sub_source: l.sub_source ?? "", project_id: l.project ? String(l.project.id) : "",
    configuration: l.configuration ?? "", budget_min: rupeesToLakh(l.budget_min), budget_max: rupeesToLakh(l.budget_max),
    purpose: l.purpose ?? "", timeline: l.timeline ?? "", estimated_value: rupeesToLakh(l.estimated_value),
    remarks: l.remarks ?? "", assigned_to_id: l.assigned_to ? String(l.assigned_to.id) : "",
  };
}

/** Convert form strings into the API's types. Empty text becomes null. */
function toPayload(f: FormState): LeadPayload {
  const text = (v: string) => (v.trim() === "" ? null : v.trim());
  return {
    name: f.name.trim(), mobile: f.mobile.trim(), alt_mobile: text(f.alt_mobile), email: text(f.email),
    city: text(f.city), source: f.source, sub_source: text(f.sub_source),
    project_id: f.project_id ? Number(f.project_id) : null, configuration: text(f.configuration),
    budget_min: lakhToRupees(f.budget_min), budget_max: lakhToRupees(f.budget_max),
    purpose: text(f.purpose), timeline: text(f.timeline), estimated_value: lakhToRupees(f.estimated_value),
    remarks: text(f.remarks),
  };
}

const enoughDigits = (v: string) => v.replace(/\D/g, "").length >= 10;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-white p-5 md:p-6">
      <h2 className="mb-4 font-semibold text-ink">{title}</h2>
      <div className="grid gap-4 md:grid-cols-2">{children}</div>
    </section>
  );
}

function LeadForm({ initial, existing }: { initial: FormState; existing?: LeadDetail }) {
  const me = useCurrentUser();
  const navigate = useNavigate();
  const isManager = me.role === "admin" || me.role === "manager";
  const projects = useProjects();
  const people = useAssignableUsers(isManager && !existing);
  const create = useCreateLead();
  const update = useUpdateLead();

  const [f, setF] = useState<FormState>(initial);
  const [duplicates, setDuplicates] = useState<Duplicate[]>([]);
  const set = (k: keyof FormState) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function runDuplicateCheck() {
    const body = {
      mobile: enoughDigits(f.mobile) ? f.mobile : undefined,
      alt_mobile: enoughDigits(f.alt_mobile) ? f.alt_mobile : undefined,
      email: f.email.includes("@") ? f.email.trim() : undefined,
      exclude_id: existing?.id,
    };
    if (!body.mobile && !body.alt_mobile && !body.email) return setDuplicates([]);
    try {
      setDuplicates(await checkDuplicates(body));
    } catch {
      /* invalid number etc. — the form's own validation will explain on save */
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const payload = toPayload(f);
    if (existing) {
      // Send only what changed.
      const before = toPayload(initial);
      const changes = Object.fromEntries(Object.entries(payload).filter(([k, v]) => before[k] !== v));
      if (Object.keys(changes).length === 0) return navigate(`/leads/${existing.id}`);
      update.mutate({ id: existing.id, changes }, { onSuccess: () => navigate(`/leads/${existing.id}`) });
    } else {
      if (isManager && f.assigned_to_id) payload.assigned_to_id = Number(f.assigned_to_id);
      create.mutate(payload, {
        onSuccess: ({ lead, duplicates: d }) => navigate(`/leads/${lead.id}`, { state: { duplicates: d } }),
      });
    }
  }

  const mutation = existing ? update : create;
  const projectList = projects.data ?? [];
  const currentProjectMissing = existing?.project && !projectList.some((p) => p.id === existing.project?.id);

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      {mutation.isError && <Alert>{errorMessage(mutation.error)}</Alert>}

      <Section title="Customer">
        <TextInput label="Full name" value={f.name} onChange={set("name")} required autoFocus={!existing} maxLength={150} />
        <TextInput label="Mobile" type="tel" inputMode="tel" value={f.mobile} onChange={set("mobile")}
          onBlur={runDuplicateCheck} placeholder="98765 43210" required />
        <TextInput label="Alternate mobile" type="tel" inputMode="tel" value={f.alt_mobile} onChange={set("alt_mobile")} onBlur={runDuplicateCheck} />
        <TextInput label="Email" type="email" inputMode="email" value={f.email} onChange={set("email")} onBlur={runDuplicateCheck} />
        <TextInput label="City or locality" value={f.city} onChange={set("city")} maxLength={100} />
      </Section>

      {duplicates.length > 0 && <DuplicateBanner duplicates={duplicates} />}

      <Section title="Source">
        <SelectInput label="Source" value={f.source} onChange={set("source")} required>
          <option value="" disabled>Choose a source</option>
          {SOURCES.map((s) => <option key={s} value={s}>{SOURCE_LABELS[s]}</option>)}
        </SelectInput>
        <TextInput label="Sub-source or campaign" value={f.sub_source} onChange={set("sub_source")} placeholder="e.g. Diwali offer ad" maxLength={150} />
      </Section>

      <Section title="Requirement">
        <SelectInput label="Project" value={f.project_id} onChange={set("project_id")}>
          <option value="">Not decided</option>
          {currentProjectMissing && existing?.project && <option value={existing.project.id}>{existing.project.name} (inactive)</option>}
          {projectList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </SelectInput>
        <SelectInput label="Configuration" value={f.configuration} onChange={set("configuration")}>
          <option value="">Not decided</option>
          {Object.entries(CONFIG_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </SelectInput>
        <TextInput label="Budget from (₹ lakh)" type="number" inputMode="decimal" min={0} step="0.5" value={f.budget_min} onChange={set("budget_min")} placeholder="e.g. 45" />
        <TextInput label="Budget up to (₹ lakh)" type="number" inputMode="decimal" min={0} step="0.5" value={f.budget_max} onChange={set("budget_max")} placeholder="e.g. 60" />
        <SelectInput label="Purpose" value={f.purpose} onChange={set("purpose")}>
          <option value="">Not known</option>
          {Object.entries(PURPOSE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </SelectInput>
        <SelectInput label="Planning to buy" value={f.timeline} onChange={set("timeline")}>
          <option value="">Not known</option>
          {Object.entries(TIMELINE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </SelectInput>
      </Section>

      <Section title="Sales">
        {isManager && !existing && (
          <SelectInput label="Assign to" value={f.assigned_to_id} onChange={set("assigned_to_id")}>
            <option value="">Leave unassigned</option>
            {people.data?.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
          </SelectInput>
        )}
        <TextInput label="Estimated deal value (₹ lakh)" type="number" inputMode="decimal" min={0} step="0.5"
          value={f.estimated_value} onChange={set("estimated_value")} hint="Used for the pipeline forecast" />
        <div className="md:col-span-2">
          <TextArea label="Remarks" value={f.remarks} onChange={set("remarks")} rows={3} maxLength={5000} />
        </div>
      </Section>

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Link to={existing ? `/leads/${existing.id}` : "/leads"}
          className="inline-flex min-h-11 items-center justify-center rounded-lg px-4 text-sm font-medium ring-1 ring-line hover:bg-forest-50">
          Cancel
        </Link>
        <Button type="submit" loading={mutation.isPending} disabled={!f.name.trim() || !f.mobile.trim() || !f.source}>
          {existing ? "Save changes" : "Create lead"}
        </Button>
      </div>
    </form>
  );
}

export function NewLeadPage() {
  return (
    <>
      <PageHeader title="New lead" />
      <LeadForm initial={EMPTY} />
    </>
  );
}

export function EditLeadPage() {
  const id = Number(useParams().id);
  const lead = useLead(id);
  if (lead.isPending) return <Spinner />;
  if (lead.isError) return <ErrorState message={errorMessage(lead.error, "Couldn’t load this lead.")} onRetry={() => void lead.refetch()} />;
  if (!lead.data.can_edit) return <Alert>You can view this lead but not edit it.</Alert>;
  return (
    <>
      <PageHeader title={`Edit ${lead.data.name}`} description={lead.data.lead_code} />
      <LeadForm initial={fromLead(lead.data)} existing={lead.data} />
    </>
  );
}
