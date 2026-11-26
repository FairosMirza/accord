import clsx from "clsx";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={clsx("shrink-0", className)} aria-hidden="true">
      <rect width="64" height="64" rx="16" fill="#0f5132" />
      <circle cx="25" cy="32" r="13" fill="none" stroke="#a7f3d0" strokeWidth="5" />
      <circle cx="39" cy="32" r="13" fill="none" stroke="#ffffff" strokeWidth="5" />
    </svg>
  );
}

export function Logo({ className, light }: { className?: string; light?: boolean }) {
  return (
    <span className={clsx("inline-flex items-center gap-2", className)}>
      <LogoMark className="size-7" />
      <span className={clsx("text-[17px] font-semibold tracking-tight", light ? "text-white" : "text-zinc-900")}>Accord</span>
    </span>
  );
}
