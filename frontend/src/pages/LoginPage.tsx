import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { Alert, Button, TextInput } from "../components/ui";
import { Wordmark } from "../components/Wordmark";
import { useAuth } from "../hooks/useAuth";
import { errorMessage } from "../lib/api";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to={from} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="grid min-h-dvh md:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <section className="flex flex-col justify-between bg-forest-900 px-6 pt-[max(2rem,env(safe-area-inset-top))] pb-8 md:px-12 md:py-12">
        <Wordmark />
        <p className="mt-10 max-w-sm font-display text-2xl leading-snug text-forest-100 md:text-3xl">
          Every enquiry, call and site visit, from first contact to booking.
        </p>
      </section>

      <section className="flex items-start justify-center px-6 py-10 md:items-center md:px-12">
        <form onSubmit={onSubmit} className="w-full max-w-sm space-y-5" noValidate>
          <div>
            <h1 className="font-display text-3xl text-forest-900">Sign in</h1>
            <p className="mt-1 text-sm text-muted">Use the email your admin set up for you.</p>
          </div>

          {error && <Alert>{error}</Alert>}

          <TextInput
            label="Email"
            type="email"
            autoComplete="username"
            inputMode="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
          />
          <TextInput
            label="Password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <Button type="submit" className="w-full" loading={submitting} disabled={!email || !password}>
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
          <p className="text-xs text-muted">Forgot your password? Ask an admin to reset it.</p>
        </form>
      </section>
    </div>
  );
}
