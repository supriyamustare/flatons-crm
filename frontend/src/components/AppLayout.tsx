import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { Ellipsis, LogOut, X } from "lucide-react";
import { useAuth, useCurrentUser } from "../hooks/useAuth";
import { mobileNavFor, navFor } from "../lib/nav";
import type { NavItem } from "../lib/nav";
import { useInboxCount } from "../hooks/useInbox";
import { QuickSearch } from "./QuickSearch";
import { ROLE_LABELS } from "../lib/types";
import { NotificationBell } from "./NotificationBell";
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
        <div className="flex items-center justify-between pt-6 pr-3 pb-7 pl-6">
          <Wordmark />
          <NotificationBell align="left" />
        </div>
        <nav aria-label="Main" className="flex-1 space-y-1 px-3">
          {items.map(({ to, label, icon: Icon, badge }) => (
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
              <NavBadge kind={badge} />
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
          <div className="flex items-center gap-1">
            <NotificationBell />
            <button
            type="button"
            onClick={() => void logout()}
            className="flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-sm text-forest-100/80"
          >
            <LogOut className="size-4" aria-hidden />
            Sign out
          </button>
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 pt-6 pb-28 md:px-10 md:pt-10 md:pb-10">
          {user.role !== "docs" && <QuickSearch />}
          <Outlet />
        </main>
      </div>

      {/* Mobile bottom navigation */}
      <MobileNav />
    </div>
  );
}


/** Phone bottom bar. Items that don't fit live in a "More" sheet. */
function MobileNav() {
  const user = useCurrentUser();
  const { logout } = useAuth();
  const { bar, more } = mobileNavFor(user.role);
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const moreActive = more.some((i) => location.pathname.startsWith(i.to));

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const tab = "relative flex min-h-16 flex-1 flex-col items-center justify-center gap-1 text-[11px]";
  return (
    <>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="More">
          <div className="absolute inset-0 bg-forest-950/50" onClick={() => setOpen(false)} aria-hidden />
          <div className="absolute inset-x-0 bottom-0 rounded-t-2xl bg-white p-3 pb-[calc(5rem+env(safe-area-inset-bottom))] shadow-xl">
            <div className="flex items-center justify-between px-2 pb-2">
              <p className="text-sm text-muted">{user.full_name}</p>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close" className="grid size-11 place-items-center rounded-lg text-muted">
                <X className="size-5" />
              </button>
            </div>
            <ul>
              {more.map(({ to, label, icon: Icon }) => (
                <li key={to}>
                  <NavLink to={to} className={({ isActive }) => cx(
                    "flex min-h-12 items-center gap-3 rounded-lg px-3 text-base",
                    isActive ? "bg-forest-50 font-medium text-forest-900" : "text-ink")}>
                    <Icon className="size-5 text-forest-800" aria-hidden />
                    {label}
                  </NavLink>
                </li>
              ))}
              <li>
                <button type="button" onClick={() => void logout()} className="flex min-h-12 w-full items-center gap-3 rounded-lg px-3 text-base text-ink">
                  <LogOut className="size-5 text-forest-800" aria-hidden />
                  Sign out
                </button>
              </li>
            </ul>
          </div>
        </div>
      )}
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-[45] flex border-t border-forest-800 bg-forest-900 pb-[env(safe-area-inset-bottom)] md:hidden">
        {bar.map(({ to, label, icon: Icon, badge }) => (
          <NavLink key={to} to={to} end={to === "/"}
            className={({ isActive }) => cx(tab, isActive && !open ? "text-gold-300" : "text-forest-100/70")}>
            <Icon className="size-5" aria-hidden />
            {label}
            <NavBadge kind={badge} compact />
          </NavLink>
        ))}
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
          className={cx(tab, open || moreActive ? "text-gold-300" : "text-forest-100/70")}>
          <Ellipsis className="size-5" aria-hidden />
          More
        </button>
      </nav>
    </>
  );
}


/** Live count beside a menu item (e.g. new enquiries waiting). Hidden at zero. */
function NavBadge({ kind, compact = false }: { kind?: NavItem["badge"]; compact?: boolean }) {
  const user = useCurrentUser();
  const count = useInboxCount(kind === "inbox" && (user.role === "admin" || user.role === "manager"));
  const n = count.data ?? 0;
  if (!kind || n === 0) return null;
  return (
    <span className={cx("rounded-full bg-gold-500 px-1.5 text-xs font-semibold text-forest-950", compact ? "absolute top-1.5 ml-7 min-w-5 text-center text-[10px]" : "ml-auto")}>
      <span aria-hidden>{n > 99 ? "99+" : n}</span>
      <span className="sr-only">{`, ${n} waiting`}</span>
    </span>
  );
}
