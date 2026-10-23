import { useState } from "react";
import { Alert, Badge, Button, ErrorState, PageHeader, Spinner, TextInput } from "../components/ui";
import { useProjects, useSaveProject } from "../hooks/useLeads";
import { errorMessage } from "../lib/api";

export function ProjectsPage() {
  const projects = useProjects(true);
  const save = useSaveProject();
  const [name, setName] = useState("");

  return (
    <>
      <PageHeader title="Projects" description="Projects leads can be linked to. Buildings and units are added in a later release." />
      <form
        className="mb-6 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-white p-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ name: name.trim() }, { onSuccess: () => setName("") });
        }}
      >
        <div className="min-w-0 flex-1 basis-60">
          <TextInput label="New project name" value={name} onChange={(e) => setName(e.target.value)} maxLength={150} />
        </div>
        <Button type="submit" loading={save.isPending} disabled={!name.trim()}>Add project</Button>
      </form>
      {save.isError && <div className="mb-4"><Alert>{errorMessage(save.error)}</Alert></div>}

      {projects.isPending && <Spinner />}
      {projects.isError && <ErrorState message={errorMessage(projects.error)} onRetry={() => void projects.refetch()} />}
      {projects.isSuccess && projects.data.length === 0 && (
        <p className="rounded-xl border border-dashed border-line bg-white px-6 py-10 text-center text-sm text-muted">
          No projects yet. Add the first one above so the sales team can tag leads with it.
        </p>
      )}
      {projects.isSuccess && projects.data.length > 0 && (
        <ul className="divide-y divide-line rounded-xl border border-line bg-white">
          {projects.data.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-3">
              <span className={p.is_active ? "font-medium" : "text-muted"}>{p.name}</span>
              <span className="flex items-center gap-2">
                {!p.is_active && <Badge tone="muted">Hidden</Badge>}
                <Button variant="ghost" onClick={() => save.mutate({ id: p.id, is_active: !p.is_active })}>
                  {p.is_active ? "Hide" : "Show"}
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
