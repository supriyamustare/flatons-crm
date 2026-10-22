import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, PageHeader, TextInput } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { useChangeMyPassword } from "../hooks/useUsers";
import { errorMessage } from "../lib/api";
import { ROLE_LABELS } from "../lib/types";

export function AccountPage() {
  const user = useCurrentUser();
  const change = useChangeMyPassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLocalError(null);
    if (next !== confirm) {
      setLocalError("The new passwords don’t match.");
      return;
    }
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          setConfirm("");
        },
      },
    );
  }

  const error = localError ?? (change.isError ? errorMessage(change.error) : null);

  return (
    <>
      <PageHeader title="My account" />
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-line bg-white p-5 md:p-6">
          <h2 className="font-semibold text-ink">Profile</h2>
          <dl className="mt-4 space-y-3 text-sm">
            <div>
              <dt className="text-muted">Name</dt>
              <dd className="text-ink">{user.full_name}</dd>
            </div>
            <div>
              <dt className="text-muted">Email</dt>
              <dd className="break-all text-ink">{user.email}</dd>
            </div>
            <div>
              <dt className="text-muted">Role</dt>
              <dd className="text-ink">{ROLE_LABELS[user.role]}</dd>
            </div>
          </dl>
          <p className="mt-4 text-xs text-muted">To change your name or role, ask an admin.</p>
        </section>

        <form onSubmit={onSubmit} className="space-y-4 rounded-xl border border-line bg-white p-5 md:p-6">
          <h2 className="font-semibold text-ink">Change password</h2>
          {error && <Alert>{error}</Alert>}
          {change.isSuccess && (
            <Alert tone="success">Password changed. You’ve been signed out on your other devices.</Alert>
          )}
          <TextInput
            label="Current password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
          <TextInput
            label="New password"
            type="password"
            autoComplete="new-password"
            hint="At least 8 characters"
            minLength={8}
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
          <TextInput
            label="Repeat new password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
          <Button type="submit" loading={change.isPending} disabled={!current || next.length < 8 || !confirm}>
            Change password
          </Button>
        </form>
      </div>
    </>
  );
}
