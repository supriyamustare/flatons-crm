import { Navigate, Outlet, useLocation } from "react-router";
import { useAuth } from "../hooks/useAuth";
import type { Role } from "../lib/types";
import { Spinner } from "./ui";

/** Sends signed-out visitors to /login, remembering where they were going. */
export function RequireAuth() {
  const { user, status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="grid min-h-dvh place-items-center">
        <Spinner label="Checking your session" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

/** Shows a no-access page to roles that can't use this section.
 *  The API enforces the same rule; this only keeps the UI honest. */
export function RequireRole({ roles }: { roles: Role[] }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role)) {
    return (
      <div className="py-20 text-center">
        <h1 className="font-display text-2xl text-forest-900">You don’t have access to this page</h1>
        <p className="mt-2 text-sm text-muted">Ask an admin if you think you should.</p>
      </div>
    );
  }
  return <Outlet />;
}
