import type { Excess, FinanceStateName, Group, NextStep, Status } from "../api/types";

export function money(amount: number | string | null | undefined, currency = "USD", opts: { compact?: boolean; cents?: boolean } = {}): string {
  if (amount === null || amount === undefined || amount === "") return "–";
  const n = typeof amount === "string" ? Number(amount) : amount;
  if (!Number.isFinite(n)) return "–";
  const showCents = opts.cents ?? (!opts.compact && Math.round(n) !== n && Math.abs(n) < 100000);
  const num = new Intl.NumberFormat("en-US", {
    notation: opts.compact ? "compact" : "standard",
    maximumFractionDigits: opts.compact ? 1 : showCents ? 2 : 0,
    minimumFractionDigits: showCents ? 2 : 0,
  }).format(n);
  return currency === "USD" ? `$${num}` : `${currency} ${num}`;
}

export function usd(amount: number | string | null | undefined, compact = false): string {
  return money(amount, "USD", { compact, cents: false });
}

/** "$750 over approval", in the approved currency when every invoice is in it. */
export function overApproval(e: Excess): string {
  return `${e.over_amount !== null ? money(e.over_amount, e.currency) : usd(e.over_usd)} over approval`;
}

/** The next step on an invoice difference, worded for whoever is reading it. */
export function nextStepText(step: NextStep, meId?: number): string {
  if (!step.owner || step.owner.id !== meId) return step.label;
  return {
    requester: "Your next step: review the invoice difference",
    approval: "Your approval is needed for the revised total",
    finance: "Your next step: query the invoice with the supplier",
    corrected_invoice: step.label,
  }[step.kind];
}

export function signedPct(n: number): string {
  const r = Math.round(n);
  return `${r > 0 ? "+" : ""}${r}%`;
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
const shortDateFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const dateTimeFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

export function date(value: string | null | undefined, short = false): string {
  if (!value) return "–";
  const d = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  if (short && d.getFullYear() === new Date().getFullYear()) return shortDateFmt.format(d);
  return dateFmt.format(d);
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "–";
  return dateTimeFmt.format(new Date(value));
}

export function ago(value: string | null | undefined): string {
  if (!value) return "";
  const diff = (Date.now() - new Date(value).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  const days = Math.floor(diff / 86400);
  if (days < 7) return days === 1 ? "yesterday" : `${days} days ago`;
  return date(value, true);
}

export function waitingFor(value: string | null | undefined): string {
  if (!value) return "";
  const hours = (Date.now() - new Date(value).getTime()) / 3_600_000;
  if (hours < 1) return "under an hour";
  if (hours < 24) return `${Math.floor(hours)} h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day" : `${days} days`;
}

export type Tone = "zinc" | "slate" | "amber" | "orange" | "green" | "rose" | "sky" | "violet" | "indigo" | "brand";

export const TONE_CLASSES: Record<Tone, string> = {
  zinc: "bg-zinc-100 text-zinc-700 ring-zinc-200",
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  orange: "bg-orange-50 text-orange-800 ring-orange-200",
  green: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  rose: "bg-rose-50 text-rose-700 ring-rose-200",
  sky: "bg-sky-50 text-sky-800 ring-sky-200",
  violet: "bg-violet-50 text-violet-800 ring-violet-200",
  indigo: "bg-indigo-50 text-indigo-800 ring-indigo-200",
  brand: "bg-brand-50 text-brand-800 ring-brand-200",
};

export const STATUS: Record<Status, { label: string; tone: Tone }> = {
  draft: { label: "Draft", tone: "zinc" },
  pending: { label: "Waiting for approval", tone: "amber" },
  returned: { label: "Changes requested", tone: "orange" },
  approved: { label: "Approved", tone: "green" },
  rejected: { label: "Not approved", tone: "rose" },
  withdrawn: { label: "Withdrawn", tone: "zinc" },
  cancelled: { label: "Cancelled", tone: "zinc" },
  closed: { label: "Closed", tone: "slate" },
};

export const FINANCE_STATE: Record<FinanceStateName, { label: string; tone: Tone }> = {
  awaiting_invoice: { label: "Awaiting invoice", tone: "sky" },
  awaiting_payment: { label: "Awaiting payment", tone: "violet" },
  paid: { label: "Paid", tone: "green" },
  closed: { label: "Closed", tone: "slate" },
};

export const GROUP: Record<Group, { label: string; tone: Tone; bar: string; dot: string }> = {
  it: { label: "IT", tone: "indigo", bar: "bg-indigo-500", dot: "bg-indigo-500" },
  travel: { label: "Travel", tone: "sky", bar: "bg-sky-400", dot: "bg-sky-400" },
  general: { label: "General", tone: "amber", bar: "bg-amber-400", dot: "bg-amber-400" },
};

export function recurringLabel(r: { payment_type: string; billing_period: string | null; term_months: number | null; amount: number; currency: string }): string | null {
  if (r.payment_type !== "recurring") return null;
  const per = { monthly: "month", quarterly: "quarter", annually: "year" }[r.billing_period ?? "monthly"];
  const term = r.term_months ? (r.term_months % 12 === 0 ? `${r.term_months / 12} year${r.term_months > 12 ? "s" : ""}` : `${r.term_months} months`) : "rolling";
  return `${money(r.amount, r.currency)} per ${per}, ${term}`;
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function firstName(name: string): string {
  return name.split(" ")[0];
}

export const ROLE_NAMES: Record<string, string> = {
  admin: "Administrator",
  finance: "Finance",
  finance_admin: "Finance lead",
  auditor: "Auditor",
  executive: "Executive",
  coo: "COO",
  ceo: "CEO",
};
