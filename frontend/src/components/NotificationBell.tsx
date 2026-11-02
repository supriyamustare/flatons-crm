import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Bell } from "lucide-react";
import { useMarkAllRead, useMarkRead, useNotifications } from "../hooks/useNotifications";
import type { AppNotification } from "../hooks/useNotifications";
import { formatDateTime } from "../lib/api";
import { cx } from "./ui";

export function NotificationBell({ align = "right" }: { align?: "left" | "right" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const notifications = useNotifications();
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();
  const unread = notifications.data?.unread_count ?? 0;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function openItem(n: AppNotification) {
    if (!n.read_at) markRead.mutate(n.id);
    setOpen(false);
    if (n.link) navigate(n.link);
  }

  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        className="relative grid size-11 place-items-center rounded-lg text-forest-100/90 hover:bg-forest-800/60 hover:text-white">
        <Bell className="size-5" aria-hidden />
        {unread > 0 && (
          <span aria-hidden className="absolute top-1.5 right-1.5 grid min-w-5 place-items-center rounded-full bg-gold-500 px-1 text-[11px] font-semibold text-forest-950">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className={cx(
          "fixed inset-x-3 top-[calc(env(safe-area-inset-top)+3.75rem)] z-50 max-h-[70dvh] overflow-y-auto rounded-xl bg-white text-ink shadow-xl ring-1 ring-line",
          "md:absolute md:inset-x-auto md:top-12 md:w-96", align === "left" ? "md:left-0" : "md:right-0",
        )}>
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 className="font-semibold">Notifications</h2>
            {unread > 0 && (
              <button type="button" className="text-sm text-forest-700 underline" onClick={() => markAll.mutate()}>
                Mark all as read
              </button>
            )}
          </div>
          {notifications.data?.items.length ? (
            <ul className="divide-y divide-line">
              {notifications.data.items.map((n) => (
                <li key={n.id}>
                  <button type="button" onClick={() => openItem(n)}
                    className={cx("flex w-full gap-3 px-4 py-3 text-left hover:bg-paper", !n.read_at && "bg-gold-100/40")}>
                    <span aria-hidden className={cx("mt-1.5 size-2 shrink-0 rounded-full", n.read_at ? "bg-transparent" : "bg-gold-500")} />
                    <span className="min-w-0">
                      <span className={cx("block text-sm", !n.read_at && "font-medium")}>{n.title}</span>
                      {n.body && <span className="block text-sm text-muted">{n.body}</span>}
                      <span className="mt-0.5 block text-xs text-muted">{formatDateTime(n.created_at)}</span>
                      {!n.read_at && <span className="sr-only">Unread</span>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-4 py-8 text-center text-sm text-muted">You’re all caught up.</p>
          )}
        </div>
      )}
    </div>
  );
}
