import { NavLink, Outlet } from "react-router";
import { LogOut } from "lucide-react";
import { useAuth, useCurrentUser } from "../hooks/useAuth";
import { navFor } from "../lib/nav";
import { ROLE_LABELS } from "../lib/types";
import { cx } from "./ui";
import { Wordmark } from "./Wordmark";

export function AppLayout() {
  const user = useCurrentUser();
  const { logout } = useAuth();
  const items = navFor(user.role);

  return (
    <div className="min-h-dvh md:flex">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col bg-forest-900 text-forest-100 md:flex">
        <div className="px-6 pt-7 pb-8">
          <Wordmark />
        </div>
        <nav aria-label="Main" className="flex-1 space-y-1 px-3">
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cx(
                  "flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm transition-colors",
                  isActive
                    ? "bg-forest-800 text-gold-300 shadow-[inset_3px_0_0_var(--color-gold-500)]"
                    : "text-forest-100/80 hover:bg-forest-800/60 hover:text-white",
                )
              }
            >
              <Icon className="size-[18px]" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-forest-800 px-4 py-4">
          <p className="truncate text-sm font-medium text-white">{user.full_name}</p>
          <p className="text-xs text-forest-100/70">{ROLE_LABELS[user.role]}</p>
          <button
            type="button"
            onClick={() => void logout()}
            className="mt-3 flex min-h-10 w-full items-center gap-2 rounded-lg px-2 text-sm text-forest-100/80 hover:bg-forest-800/60 hover:text-white"
          >
            <LogOut className="size-4" aria-hidden />
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <header className="sticky top-0 z-30 flex items-center justify-between bg-forest-900 px-4 pt-[env(safe-area-inset-top)] md:hidden">
          <div className="flex h-14 items-center">
            <Wordmark />
          </div>
          <button
            type="button"
            onClick={() => void logout()}
            className="flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-sm text-forest-100/80"
          >
            <LogOut className="size-4" aria-hidden />
            Sign out
          </button>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 pt-6 pb-28 md:px-10 md:pt-10 md:pb-10">
          <Outlet />
        </main>
      </div>

      {/* Mobile bottom navigation */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-forest-800 bg-forest-900 pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        {items
          .filter((i) => i.mobile)
          .map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cx(
                  "flex min-h-16 flex-1 flex-col items-center justify-center gap-1 text-[11px]",
                  isActive ? "text-gold-300" : "text-forest-100/70",
                )
              }
            >
              <Icon className="size-5" aria-hidden />
              {label}
            </NavLink>
          ))}
      </nav>
    </div>
  );
}
