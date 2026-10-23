import { useEffect, useId } from "react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { CircleAlert, LoaderCircle, RefreshCw, X } from "lucide-react";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-forest-900 text-white hover:bg-forest-800 disabled:bg-forest-700/60",
  secondary: "bg-white text-ink ring-1 ring-line hover:bg-forest-50",
  danger: "bg-danger text-white hover:bg-danger/90",
  ghost: "text-forest-800 hover:bg-forest-50",
};

export function Button({
  variant = "primary",
  loading = false,
  className,
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      className={cx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-medium transition-colors disabled:cursor-not-allowed",
        VARIANTS[variant],
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  htmlFor: string;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

const inputClass =
  "block min-h-11 w-full rounded-lg border border-line bg-white px-3 text-base text-ink placeholder:text-muted/70 focus:border-forest-700 focus:outline-none focus:ring-2 focus:ring-forest-700/20 disabled:bg-paper disabled:text-muted md:text-sm";

export function TextInput({
  label,
  hint,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} htmlFor={props.id ?? id}>
      <input id={props.id ?? id} className={inputClass} {...props} />
    </Field>
  );
}

export function TextArea({
  label,
  hint,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: ReactNode }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} htmlFor={props.id ?? id}>
      <textarea id={props.id ?? id} rows={3} className={`${inputClass} py-2.5`} {...props} />
    </Field>
  );
}

export function SelectInput({
  label,
  hint,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string; hint?: ReactNode }) {
  const id = useId();
  return (
    <Field label={label} hint={hint} htmlFor={props.id ?? id}>
      <select id={props.id ?? id} className={inputClass} {...props}>
        {children}
      </select>
    </Field>
  );
}

export function Alert({ children, tone = "error" }: { children: ReactNode; tone?: "error" | "success" }) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cx(
        "flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm",
        tone === "error" ? "bg-danger-soft text-danger" : "bg-forest-50 text-forest-800",
      )}
    >
      {tone === "error" && <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />}
      <span>{children}</span>
    </div>
  );
}

export type BadgeTone = "neutral" | "gold" | "muted" | "solid" | "danger";

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: BadgeTone }) {
  const tones: Record<BadgeTone, string> = {
    neutral: "bg-forest-50 text-forest-800 ring-forest-100",
    gold: "bg-gold-100 text-gold-600 ring-gold-300/60",
    muted: "bg-paper text-muted ring-line",
    solid: "bg-forest-900 text-gold-300 ring-forest-900",
    danger: "bg-danger-soft text-danger ring-danger/20",
  };
  return (
    <span className={cx("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1", tones[tone])}>
      {children}
    </span>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center py-16 text-muted" role="status">
      <LoaderCircle className="size-6 animate-spin" aria-hidden />
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-xl border border-line bg-white px-6 py-10 text-center">
      <p className="text-sm text-ink">{message}</p>
      <Button variant="secondary" className="mt-4" onClick={onRetry}>
        <RefreshCw className="size-4" aria-hidden />
        Try again
      </Button>
    </div>
  );
}

export function PageHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-3xl text-forest-900">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

/** Accessible modal: bottom sheet on phones, centred dialog on larger screens. */
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const titleId = useId();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <div className="absolute inset-0 bg-forest-950/50" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative max-h-[92dvh] w-full overflow-y-auto rounded-t-2xl bg-white p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-xl sm:max-w-lg sm:rounded-2xl sm:p-6"
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 id={titleId} className="text-lg font-semibold text-ink">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="-mr-2 rounded-lg p-2 text-muted hover:bg-paper"
            aria-label="Close"
          >
            <X className="size-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export { cx };
