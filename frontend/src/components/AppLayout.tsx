import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { Ellipsis, LogOut, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { useAuth, useCurrentUser } from "../hooks/useAuth";
import { mobileNavFor, navFor } from "../lib/nav";
import type { NavItem } from "../lib/nav";
import { useInboxCount } from "../hooks/useInbox";
import { QuickSearch } from "./QuickSearch";
import { ROLE_LABELS } from "../lib/types";
import { NotificationBell } from "./NotificationBell";
import { cx } from "./ui";
import { Wordmark } from "./Wordmark";

const SIDEBAR_KEY = "flatons.sidebar.collapsed";

/** Collapsed or expanded left menu, remembered in this browser. */
function useSidebarCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(SIDEBAR_KEY) === "1"; } catch { return false; }
  });
  const toggle = () => setCollapsed((c) => {
    try { localStorage.setItem(SIDEBAR_KEY, c ? "0" : "1"); } catch { /* storage unavailable: just don't remember */ }
    return !c;
  });
  return [collapsed, toggle];
}

export function AppLayout() {
  const user = useCurrentUser();
  const [collapsed, toggle] = useSidebarCollapsed();
  const items = navFor(user.role);

  return (
    <div className="min-h-dvh md:flex">
      {/* Desktop sidebar */}
      <aside id="main-sidebar" className={cx("sticky top-0 hidden h-dvh shrink-0 flex-col bg-forest-900 text-forest-100 transition-[width] duration-200 md:flex",
        collapsed ? "w-[4.5rem]" : "w-64")}>
        <div className={cx("flex shrink-0 items-center", collapsed ? "flex-col gap-0.5 px-2 py-2" : "justify-between py-3 pr-2 pl-6")}>
          {!collapsed && <Wordmark />}
          <div className={cx("flex items-center", collapsed && "flex-col gap-0.5")}>
            <NotificationBell align="left" />
            <button type="button" onClick={toggle} aria-expanded={!collapsed} aria-controls="main-sidebar"
              aria-label={collapsed ? "Expand menu" : "Collapse menu"} title={collapsed ? "Expand menu" : "Collapse menu"}
              className="grid size-9 place-items-center rounded-lg text-forest-100/80 hover:bg-forest-800/60 hover:text-white">
              {collapsed ? <PanelLeftOpen className="size-5" aria-hidden /> : <PanelLeftClose className="size-5" aria-hidden />}
            </button>
          </div>
        </div>
        {/* The list scrolls inside the dark panel if the screen is short, so items never fall off it */}
        <nav aria-label="Main" className={cx("sidebar-scroll min-h-0 flex-1 space-y-px overflow-y-auto pb-2", collapsed ? "px-2" : "px-3")}>
          {items.filter((i) => i.to !== "/account").map(({ to, label, icon: Icon, badge }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                cx(
                  "relative flex min-h-9 items-center gap-3 rounded-lg text-sm transition-colors",
                  collapsed ? "justify-center px-0" : "px-3",
                  isActive
                    ? "bg-forest-800 text-gold-300 shadow-[inset_3px_0_0_var(--color-gold-500)]"
                    : "text-forest-100/90 hover:bg-forest-800/60 hover:text-white",
                )
              }
            >
              <Icon className="size-[18px] shrink-0" aria-hidden />
              <span className={collapsed ? "sr-only" : undefined}>{label}</span>
              <NavBadge kind={badge} corner={collapsed} />
            </NavLink>
          ))}
        </nav>
        <AccountBlock compact={collapsed} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <header className="sticky top-0 z-30 flex items-center justify-between bg-forest-900 px-4 pt-[env(safe-area-inset-top)] md:hidden">
          <div className="flex h-14 items-center">
            <Wordmark />
          </div>
          <div className="flex items-center gap-1">
            <NotificationBell />
          </div>
        </header>

        <main className={cx("mx-auto w-full flex-1 px-4 pt-6 pb-28 md:px-10 md:pt-10 md:pb-10", collapsed ? "max-w-7xl" : "max-w-6xl")}>
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
            <div className="flex items-center justify-end px-2 pb-1">
              <button type="button" onClick={() => setOpen(false)} aria-label="Close" className="grid size-11 place-items-center rounded-lg text-muted">
                <X className="size-5" />
              </button>
            </div>
            <AccountBlock light />
            <ul className="mt-2">
              {more.filter((i) => i.to !== "/account").map(({ to, label, icon: Icon }) => (
                <li key={to}>
                  <NavLink to={to} className={({ isActive }) => cx(
                    "flex min-h-12 items-center gap-3 rounded-lg px-3 text-base",
                    isActive ? "bg-forest-50 font-medium text-forest-900" : "text-ink")}>
                    <Icon className="size-5 text-forest-800" aria-hidden />
                    {label}
                  </NavLink>
                </li>
              ))}
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
function NavBadge({ kind, compact = false, corner = false }: { kind?: NavItem["badge"]; compact?: boolean; corner?: boolean }) {
  const user = useCurrentUser();
  const count = useInboxCount(kind === "inbox" && (user.role === "admin" || user.role === "manager"));
  const n = count.data ?? 0;
  if (!kind || n === 0) return null;
  return (
    <span className={cx("rounded-full bg-gold-500 px-1.5 text-xs font-semibold text-forest-950",
      compact ? "absolute top-1.5 ml-7 min-w-5 text-center text-[10px]" : corner ? "absolute -top-0.5 right-1 min-w-4 px-1 text-center text-[10px]" : "ml-auto")}>
      <span aria-hidden>{n > 99 ? "99+" : n}</span>
      <span className="sr-only">{`, ${n} waiting`}</span>
    </span>
  );
}


/** "My account": who is signed in, a link to the account page, and Sign out, together in one place. */
function AccountBlock({ light = false, compact = false }: { light?: boolean; compact?: boolean }) {
  const user = useCurrentUser();
  const { logout } = useAuth();
  const initials = user.full_name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  if (compact) {
    return (
      <section aria-label="My account" className="flex shrink-0 flex-col items-center gap-0.5 border-t border-forest-800 py-1.5">
        <NavLink to="/account" title={`${user.full_name}: My account`} aria-label={`${user.full_name}, My account · ${ROLE_LABELS[user.role]}`}
          className="grid size-9 place-items-center rounded-full bg-gold-500 text-sm font-semibold text-forest-950 ring-offset-2 ring-offset-forest-900 hover:ring-2 hover:ring-gold-300">
          {initials}
        </NavLink>
        <button type="button" onClick={() => void logout()} aria-label="Sign out" title="Sign out"
          className="grid size-9 place-items-center rounded-lg text-forest-100/90 hover:bg-forest-800/60 hover:text-white">
          <LogOut className="size-4" aria-hidden />
        </button>
      </section>
    );
  }
  return (
    <section aria-label="My account" className={cx("shrink-0", light ? "rounded-xl bg-forest-50 p-2" : "border-t border-forest-800 px-3 py-2")}>
      <NavLink to="/account" className={({ isActive }) => cx(
        "flex items-center gap-3 rounded-lg px-2 py-1.5 transition-colors",
        light ? "hover:bg-white" : isActive ? "bg-forest-800" : "hover:bg-forest-800/60")}>
        <span aria-hidden className={cx("grid size-9 shrink-0 place-items-center rounded-full text-sm font-semibold",
          light ? "bg-forest-900 text-white" : "bg-gold-500 text-forest-950")}>{initials}</span>
        <span className="min-w-0">
          <span className={cx("block truncate text-sm font-medium", light ? "text-forest-900" : "text-white")}>{user.full_name}</span>
          <span className={cx("block text-xs", light ? "text-muted" : "text-forest-100/75")}>My account · {ROLE_LABELS[user.role]}</span>
        </span>
      </NavLink>
      <button type="button" onClick={() => void logout()}
        className={cx("flex min-h-9 w-full items-center gap-2 rounded-lg px-3 text-sm transition-colors",
          light ? "text-ink hover:bg-white" : "text-forest-100/90 hover:bg-forest-800/60 hover:text-white")}>
        <LogOut className="size-4" aria-hidden />
        Sign out
      </button>
    </section>
  );
}
