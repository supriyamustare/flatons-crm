import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Modal, SelectInput, TextInput } from "../../components/ui";
import { useCreateUser, useDeactivateUser, useUpdateUser } from "../../hooks/useUsers";
import type { UserChanges } from "../../hooks/useUsers";
import { errorMessage } from "../../lib/api";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, ROLES } from "../../lib/types";
import type { Role, User } from "../../lib/types";

/** Readable temporary password, e.g. "maple-river-4821". */
function generatePassword(): string {
  const words = ["maple", "river", "cedar", "harbor", "amber", "falcon", "meadow", "copper", "summit", "lotus"];
  const pick = () => words[crypto.getRandomValues(new Uint32Array(1))[0] % words.length];
  const digits = String(crypto.getRandomValues(new Uint32Array(1))[0] % 10000).padStart(4, "0");
  return `${pick()}-${pick()}-${digits}`;
}

function RoleSelect({ value, onChange, disabled }: { value: Role; onChange: (r: Role) => void; disabled?: boolean }) {
  return (
    <SelectInput
      label="Role"
      value={value}
      onChange={(e) => onChange(e.target.value as Role)}
      disabled={disabled}
      hint={ROLE_DESCRIPTIONS[value]}
    >
      {ROLES.map((r) => (
        <option key={r} value={r}>
          {ROLE_LABELS[r]}
        </option>
      ))}
    </SelectInput>
  );
}

export function AddUserModal({ onClose }: { onClose: () => void }) {
  const create = useCreateUser();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("executive");
  const [password, setPassword] = useState(generatePassword);
  const [created, setCreated] = useState<User | null>(null);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    create.mutate(
      { full_name: fullName.trim(), email: email.trim(), role, password },
      { onSuccess: setCreated },
    );
  }

  if (created) {
    return (
      <Modal title="User added" onClose={onClose}>
        <p className="text-sm text-ink">
          Share these sign-in details with {created.full_name}. They can change the password from
          My account.
        </p>
        <dl className="mt-4 space-y-2 rounded-lg bg-paper p-4 text-sm">
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Email</dt>
            <dd className="break-all font-medium">{created.email}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Temporary password</dt>
            <dd className="font-mono font-medium">{password}</dd>
          </div>
        </dl>
        <p className="mt-3 text-xs text-muted">This password won’t be shown again.</p>
        <Button className="mt-5 w-full" onClick={onClose}>
          Done
        </Button>
      </Modal>
    );
  }

  return (
    <Modal title="Add user" onClose={onClose}>
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {create.isError && <Alert>{errorMessage(create.error)}</Alert>}
        <TextInput label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} required autoFocus />
        <TextInput
          label="Email"
          type="email"
          inputMode="email"
          autoComplete="off"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <RoleSelect value={role} onChange={setRole} />
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <TextInput
              label="Temporary password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="off"
              hint="At least 8 characters"
              required
            />
          </div>
          <Button type="button" variant="secondary" className="mb-[22px]" onClick={() => setPassword(generatePassword())}>
            New
          </Button>
        </div>
        <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            loading={create.isPending}
            disabled={!fullName.trim() || !email.trim() || password.length < 8}
          >
            Add user
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function EditUserModal({ user, isSelf, onClose }: { user: User; isSelf: boolean; onClose: () => void }) {
  const update = useUpdateUser();
  const deactivate = useDeactivateUser();
  const [fullName, setFullName] = useState(user.full_name);
  const [role, setRole] = useState<Role>(user.role);
  const [newPassword, setNewPassword] = useState("");
  const [confirmingDeactivate, setConfirmingDeactivate] = useState(false);

  const changes: UserChanges = {};
  if (fullName.trim() !== user.full_name) changes.full_name = fullName.trim();
  if (role !== user.role) changes.role = role;
  if (newPassword) changes.password = newPassword;
  const hasChanges = Object.keys(changes).length > 0;

  const error = update.error ?? deactivate.error;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    update.mutate({ id: user.id, changes }, { onSuccess: onClose });
  }

  return (
    <Modal title={`Edit ${user.full_name}`} onClose={onClose}>
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {error && <Alert>{errorMessage(error)}</Alert>}
        <p className="break-all text-sm text-muted">{user.email}</p>
        <TextInput label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
        <RoleSelect value={role} onChange={setRole} disabled={isSelf} />
        {isSelf && <p className="-mt-2 text-xs text-muted">You can’t change your own role.</p>}
        <TextInput
          label="Reset password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          autoComplete="off"
          placeholder="Leave blank to keep the current password"
          hint={newPassword ? "They’ll be signed out everywhere and must use this password." : undefined}
        />
        <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            loading={update.isPending}
            disabled={!hasChanges || !fullName.trim() || (!!newPassword && newPassword.length < 8)}
          >
            Save changes
          </Button>
        </div>
      </form>

      {!isSelf && (
        <div className="mt-6 border-t border-line pt-5">
          {user.is_active ? (
            confirmingDeactivate ? (
              <div className="space-y-3">
                <p className="text-sm text-ink">
                  Deactivate {user.full_name}? They’ll be signed out right away and won’t be able to sign
                  in. Their records stay in the system.
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="danger"
                    loading={deactivate.isPending}
                    onClick={() => deactivate.mutate(user.id, { onSuccess: onClose })}
                  >
                    Deactivate
                  </Button>
                  <Button variant="secondary" onClick={() => setConfirmingDeactivate(false)}>
                    Keep active
                  </Button>
                </div>
              </div>
            ) : (
              <Button variant="ghost" className="text-danger" onClick={() => setConfirmingDeactivate(true)}>
                Deactivate user
              </Button>
            )
          ) : (
            <Button
              variant="secondary"
              loading={update.isPending}
              onClick={() => update.mutate({ id: user.id, changes: { is_active: true } }, { onSuccess: onClose })}
            >
              Reactivate user
            </Button>
          )}
        </div>
      )}
    </Modal>
  );
}
