import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { CheckCircle2, X } from "lucide-react";

interface Toast { id: number; message: string }
const ToastContext = createContext<(message: string) => void>(() => {});

/** Short confirmations ("Legal details saved") that appear in a corner and fade after a few seconds. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const show = useCallback((message: string) => {
    const id = next.current++;
    setToasts((t) => [...t.slice(-2), { id, message }]); // at most 3 on screen
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      {/* Announced politely by screen readers; sits above the phone's bottom bar */}
      <div aria-live="polite" role="status" aria-label="Notifications"
        className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 md:inset-x-auto md:right-6 md:bottom-6 md:items-end">
        {toasts.map((t) => <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />)}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  useEffect(() => { const t = setTimeout(onDismiss, 4000); return () => clearTimeout(t); }, [onDismiss]);
  return (
    <div className="pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-xl bg-forest-900 px-4 py-3 text-sm text-white shadow-lg ring-1 ring-forest-700 motion-safe:animate-[toast-in_160ms_ease-out]">
      <CheckCircle2 className="size-5 shrink-0 text-gold-300" aria-hidden />
      <p className="flex-1">{toast.message}</p>
      <button type="button" onClick={onDismiss} aria-label="Dismiss notification" className="grid size-8 place-items-center rounded-lg text-forest-100 hover:bg-forest-800">
        <X className="size-4" aria-hidden />
      </button>
    </div>
  );
}

/** Show a confirmation. Safe to call anywhere; does nothing outside the provider. */
export function useToast() {
  return useContext(ToastContext);
}
