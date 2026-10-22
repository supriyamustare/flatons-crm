import { useState } from "react";
import { Plus } from "lucide-react";
import { Badge, Button, ErrorState, PageHeader } from "../../components/ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { useUsers } from "../../hooks/useUsers";
import { errorMessage, formatDateTime } from "../../lib/api";
import { ROLE_LABELS } from "../../lib/types";
import type { User } from "../../lib/types";
import { AddUserModal, EditUserModal } from "./UserFormModals";

function StatusBadge({ active }: { active: boolean }) {
  return active ? <Badge>Active</Badge> : <Badge tone="muted">Deactivated</Badge>;
}

function RoleBadge({ user }: { user: User }) {
  return <Badge tone={user.role === "admin" ? "gold" : "neutral"}>{ROLE_LABELS[user.role]}</Badge>;
}

function LoadingRows() {
  return (
    <div className="divide-y divide-line rounded-xl border border-line bg-white" aria-busy="true" aria-label="Loading users">
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex items-center gap-4 px-5 py-4">
          <div className="h-4 w-40 animate-pulse rounded bg-forest-50" />
          <div className="h-4 w-24 animate-pulse rounded bg-forest-50" />
        </div>
      ))}
    </div>
  );
}

export function UsersPage() {
  const me = useCurrentUser();
  const users = useUsers();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);

  return (
    <>
      <PageHeader
        title="Users"
        description="Everyone who can sign in to the CRM, and what they can do."
        action={
          <Button onClick={() => setAdding(true)}>
            <Plus className="size-4" aria-hidden />
            Add user
          </Button>
        }
      />

      {users.isPending && <LoadingRows />}
      {users.isError && (
        <ErrorState message={errorMessage(users.error, "Couldn’t load users.")} onRetry={() => void users.refetch()} />
      )}

      {users.isSuccess && (
        <>
          {/* Phones: stacked list */}
          <ul className="divide-y divide-line rounded-xl border border-line bg-white md:hidden">
            {users.data.map((u) => (
              <li key={u.id}>
                <button
                  type="button"
                  onClick={() => setEditing(u)}
                  className="flex w-full items-start justify-between gap-3 px-4 py-4 text-left active:bg-paper"
                >
                  <span className="min-w-0">
                    <span className="block font-medium text-ink">
                      {u.full_name}
                      {u.id === me.id && <span className="font-normal text-muted"> (you)</span>}
                    </span>
                    <span className="block truncate text-sm text-muted">{u.email}</span>
                  </span>
                  <span className="flex shrink-0 flex-col items-end gap-1.5">
                    <RoleBadge user={u} />
                    {!u.is_active && <StatusBadge active={false} />}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          {/* Tablets and up: table */}
          <div className="hidden overflow-x-auto rounded-xl border border-line bg-white md:block">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line text-muted">
                <tr>
                  <th className="px-5 py-3 font-medium">Name</th>
                  <th className="px-5 py-3 font-medium">Role</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Last sign-in</th>
                  <th className="px-5 py-3">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {users.data.map((u) => (
                  <tr key={u.id} className={u.is_active ? "" : "text-muted"}>
                    <td className="px-5 py-3.5">
                      <div className="font-medium text-ink">
                        {u.full_name}
                        {u.id === me.id && <span className="font-normal text-muted"> (you)</span>}
                      </div>
                      <div className="text-muted">{u.email}</div>
                    </td>
                    <td className="px-5 py-3.5">
                      <RoleBadge user={u} />
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge active={u.is_active} />
                    </td>
                    <td className="px-5 py-3.5 whitespace-nowrap">{formatDateTime(u.last_login_at)}</td>
                    <td className="px-5 py-3.5 text-right">
                      <Button variant="ghost" onClick={() => setEditing(u)}>
                        Edit
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {adding && <AddUserModal onClose={() => setAdding(false)} />}
      {editing && <EditUserModal user={editing} isSelf={editing.id === me.id} onClose={() => setEditing(null)} />}
    </>
  );
}
