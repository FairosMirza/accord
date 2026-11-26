import clsx from "clsx";
import { Loader2, X } from "lucide-react";
import { cloneElement, isValidElement, useEffect, useId, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router";
import { TONE_CLASSES, type Tone } from "../lib/format";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-700 text-white hover:bg-brand-800 shadow-sm disabled:bg-brand-700/50",
  secondary: "bg-white text-zinc-800 ring-1 ring-inset ring-zinc-200 hover:bg-zinc-50 shadow-card disabled:text-zinc-400",
  ghost: "text-zinc-700 hover:bg-zinc-100 disabled:text-zinc-400",
  danger: "bg-white text-rose-700 ring-1 ring-inset ring-rose-200 hover:bg-rose-50 disabled:text-rose-300",
  subtle: "bg-brand-50 text-brand-800 hover:bg-brand-100 disabled:opacity-60",
};
const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5 rounded-lg",
  md: "h-10 px-4 text-sm gap-2 rounded-xl",
  lg: "h-12 px-5 text-[15px] gap-2 rounded-xl",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      className={clsx("inline-flex shrink-0 items-center justify-center font-medium transition-colors disabled:cursor-not-allowed", VARIANTS[variant], SIZES[size], className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function ButtonLink({ to, variant = "secondary", size = "md", icon, className, children }: { to: string; variant?: Variant; size?: Size; icon?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <Link to={to} className={clsx("inline-flex shrink-0 items-center justify-center font-medium transition-colors", VARIANTS[variant], SIZES[size], className)}>
      {icon}
      {children}
    </Link>
  );
}

export function Card({ className, children, padded = true }: { className?: string; children: ReactNode; padded?: boolean }) {
  return <div className={clsx("rounded-2xl bg-white shadow-card ring-1 ring-zinc-900/[0.06]", padded && "p-4 sm:p-5", className)}>{children}</div>;
}

export function CardHeader({ title, subtitle, action, icon }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="mb-3 flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-2.5">
        {icon && <div className="mt-0.5 text-zinc-400">{icon}</div>}
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-zinc-900">{title}</h2>
          {subtitle && <p className="mt-0.5 text-[13px] text-zinc-500">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

export function Badge({ tone = "zinc", children, className, dot }: { tone?: Tone; children: ReactNode; className?: string; dot?: boolean }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[12px] font-medium ring-1 ring-inset", TONE_CLASSES[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current opacity-70" />}
      {children}
    </span>
  );
}

const AVATAR_COLORS = ["bg-emerald-100 text-emerald-800", "bg-sky-100 text-sky-800", "bg-amber-100 text-amber-800", "bg-violet-100 text-violet-800", "bg-rose-100 text-rose-800", "bg-teal-100 text-teal-800", "bg-indigo-100 text-indigo-800", "bg-lime-100 text-lime-800"];

export function Avatar({ name, initials, size = "md", className }: { name: string; initials?: string; size?: "xs" | "sm" | "md" | "lg"; className?: string }) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const text = initials ?? name.split(" ").map((p) => p[0]).slice(0, 2).join("");
  const sizes = { xs: "size-5 text-[9px]", sm: "size-7 text-[11px]", md: "size-9 text-[13px]", lg: "size-12 text-base" };
  return <span className={clsx("inline-flex shrink-0 select-none items-center justify-center rounded-full font-semibold", AVATAR_COLORS[h % AVATAR_COLORS.length], sizes[size], className)}>{text.toUpperCase()}</span>;
}

export function Field({ label, hint, error, children, htmlFor, optional }: { label: ReactNode; hint?: ReactNode; error?: string | null; children: ReactNode; htmlFor?: string; optional?: boolean }) {
  const autoId = useId();
  // Link the label (and hint) to a single form control child, so screen readers announce them.
  const single = isValidElement<{ id?: string; "aria-describedby"?: string }>(children) ? children : null;
  const id = htmlFor ?? single?.props.id ?? autoId;
  const hintId = `${id}-hint`;
  const control = single && !single.props.id ? cloneElement(single, { id, "aria-describedby": hint || error ? hintId : undefined }) : children;
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="flex items-baseline justify-between text-[13px] font-medium text-zinc-800">
        <span>{label}</span>
        {optional && <span className="text-[12px] font-normal text-zinc-400">Optional</span>}
      </label>
      {control}
      {hint && !error && (
        <p id={hintId} className="text-[12px] leading-snug text-zinc-500">
          {hint}
        </p>
      )}
      {error && (
        <p id={hintId} className="text-[12px] font-medium text-rose-600">
          {error}
        </p>
      )}
    </div>
  );
}

const inputBase = "block w-full rounded-xl border-0 bg-white px-3 text-[15px] text-zinc-900 shadow-card ring-1 ring-inset ring-zinc-200 placeholder:text-zinc-400 focus:ring-2 focus:ring-inset focus:ring-brand-500 disabled:bg-zinc-50 disabled:text-zinc-500 sm:text-sm";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={clsx(inputBase, "h-11 sm:h-10", className)} {...rest} />;
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={clsx(inputBase, "py-2.5", className)} rows={3} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={clsx(inputBase, "h-11 appearance-none bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 20 20%22 fill=%22%2371717a%22><path d=%22M5.5 7.5 10 12l4.5-4.5%22 stroke=%22%2371717a%22 stroke-width=%221.6%22 fill=%22none%22 stroke-linecap=%22round%22/></svg>')] bg-[length:18px] bg-[right_10px_center] bg-no-repeat pr-9 sm:h-10", className)} {...rest}>
      {children}
    </select>
  );
}

export function Toggle({ checked, onChange, label, description, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; description?: ReactNode; disabled?: boolean }) {
  const id = useId();
  return (
    <label htmlFor={id} className={clsx("flex cursor-pointer items-start justify-between gap-4", disabled && "cursor-not-allowed opacity-60")}>
      <span className="min-w-0">
        <span className="block text-[14px] font-medium text-zinc-800">{label}</span>
        {description && <span className="mt-0.5 block text-[12px] leading-snug text-zinc-500">{description}</span>}
      </span>
      <span className="relative mt-0.5 inline-flex shrink-0">
        <input id={id} type="checkbox" className="peer sr-only" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
        <span className="h-6 w-10 rounded-full bg-zinc-200 transition-colors peer-checked:bg-brand-600 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand-500" />
        <span className="absolute left-0.5 top-0.5 size-5 rounded-full bg-white shadow transition-transform peer-checked:translate-x-4" />
      </span>
    </label>
  );
}

export function Segmented<T extends string>({ value, onChange, options, className }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode; count?: number }[]; className?: string }) {
  return (
    <div className={clsx("inline-flex rounded-xl bg-zinc-100 p-1", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={clsx("flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] font-medium transition", value === o.value ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-600 hover:text-zinc-900")}
        >
          {o.label}
          {o.count !== undefined && <span className={clsx("rounded-full px-1.5 text-[11px] tabular", value === o.value ? "bg-zinc-100" : "bg-zinc-200/70")}>{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Modal({ open, onClose, title, description, children, footer, wide }: { open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.querySelector<HTMLElement>("input, textarea, select, button[data-autofocus]")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4" role="dialog" aria-modal="true">
      <div className="animate-fade absolute inset-0 bg-zinc-950/40 backdrop-blur-[2px]" onClick={onClose} />
      <div ref={panel} className={clsx("animate-sheet relative flex max-h-[92dvh] w-full flex-col rounded-t-3xl bg-white shadow-pop sm:rounded-2xl", wide ? "sm:max-w-2xl" : "sm:max-w-md")}>
        <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-zinc-200 sm:hidden" />
        <div className="flex items-start justify-between gap-4 px-5 pb-2 pt-4 sm:pt-5">
          <div>
            <h3 className="text-[17px] font-semibold text-zinc-900">{title}</h3>
            {description && <p className="mt-1 text-[13px] leading-snug text-zinc-500">{description}</p>}
          </div>
          <button type="button" onClick={onClose} className="-mr-1 rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>
        <div className="overflow-y-auto px-5 pb-4 pt-1">{children}</div>
        {footer && <div className="pb-safe flex gap-2 border-t border-zinc-100 px-5 pt-3 sm:pb-4">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      {icon && <div className="mb-3 rounded-2xl bg-zinc-100 p-3 text-zinc-500">{icon}</div>}
      <p className="text-[15px] font-semibold text-zinc-800">{title}</p>
      {children && <p className="mt-1 max-w-sm text-[13px] leading-relaxed text-zinc-500">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("size-5 animate-spin text-zinc-400", className)} />;
}

export function PageLoader() {
  return (
    <div className="flex h-64 items-center justify-center">
      <Spinner className="size-6" />
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return <div className="rounded-xl bg-rose-50 px-4 py-3 text-[13px] text-rose-700 ring-1 ring-inset ring-rose-200">{message}</div>;
}

export function PageHeader({ title, subtitle, actions, back }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; back?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:mb-6 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {back}
        <h1 className="text-[22px] font-semibold tracking-tight text-zinc-900 sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-[14px] text-zinc-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: ReactNode; value: ReactNode; hint?: ReactNode; tone?: "default" | "warn" }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[12px] font-medium uppercase tracking-wide text-zinc-500">{label}</p>
      <p className={clsx("mt-1 truncate text-[22px] font-semibold tabular tracking-tight", tone === "warn" ? "text-amber-700" : "text-zinc-900")}>{value}</p>
      {hint && <p className="mt-0.5 truncate text-[12px] text-zinc-500">{hint}</p>}
    </div>
  );
}

export function Progress({ value, max, className, over }: { value: number; max: number; className?: string; over?: boolean }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className={clsx("h-2 overflow-hidden rounded-full bg-zinc-100", className)}>
      <div className={clsx("h-full rounded-full transition-all", over ? "bg-rose-500" : "bg-brand-500")} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="divide-y divide-zinc-100">
      {items.map(([k, v], i) => (
        <div key={i} className="flex justify-between gap-4 py-2.5 text-[14px]">
          <dt className="shrink-0 text-zinc-500">{k}</dt>
          <dd className="min-w-0 text-right font-medium text-zinc-900">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
