import clsx from "clsx";
import { Check, Clock, CornerUpLeft, Eye, Lock, Paperclip, Repeat, UserCheck, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { useAction, useLookups } from "../api/hooks";
import type { RequestDetail, RequestSummary, Step } from "../api/types";
import { ago, dateTime, FINANCE_STATE, GROUP, money, recurringLabel, STATUS, usd, waitingFor } from "../lib/format";
import { Avatar, Badge, Button, Field, Modal, Textarea } from "./ui";

export function StatusPill({ r }: { r: Pick<RequestSummary, "status" | "finance" | "amendment_in_progress"> }) {
  if (r.amendment_in_progress) return <Badge tone="amber" dot>Change awaiting approval</Badge>;
  if (r.status === "approved" && r.finance) {
    const f = FINANCE_STATE[r.finance.state];
    return (
      <Badge tone={f.tone} dot>
        {r.finance.state === "awaiting_invoice" ? "Approved" : f.label}
      </Badge>
    );
  }
  const s = STATUS[r.status];
  return (
    <Badge tone={s.tone} dot>
      {s.label}
    </Badge>
  );
}

export function Amount({ r, size = "md" }: { r: Pick<RequestSummary, "total_amount" | "currency" | "total_usd">; size?: "md" | "lg" }) {
  return (
    <div className="text-right">
      <p className={clsx("font-semibold tabular text-zinc-900", size === "lg" ? "text-[26px] tracking-tight" : "text-[15px]")}>{money(r.total_amount, r.currency)}</p>
      {r.currency !== "USD" && <p className={clsx("tabular text-zinc-500", size === "lg" ? "text-[14px]" : "text-[12px]")}>≈ {usd(r.total_usd)}</p>}
    </div>
  );
}

export function RequestRow({ r, showRequester = true, emphasiseWaiting }: { r: RequestSummary; showRequester?: boolean; emphasiseWaiting?: boolean }) {
  const recurring = recurringLabel(r);
  return (
    <Link to={`/requests/${r.ref}`} className="group flex gap-3 px-4 py-3.5 transition-colors hover:bg-zinc-50/80 sm:px-5">
      {showRequester && <Avatar name={r.requester.name} initials={r.requester.initials} className="mt-0.5" />}
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-[14.5px] font-semibold text-zinc-900 group-hover:text-brand-800">
              {r.is_confidential && <Lock className="mr-1 inline size-3.5 -translate-y-px text-zinc-400" />}
              {r.title}
            </p>
            <p className="mt-0.5 truncate text-[12.5px] text-zinc-500">
              {showRequester && <>{r.requester.name} · </>}
              {r.supplier ?? "No supplier"} · <span className="tabular">{r.ref}</span>
            </p>
          </div>
          <Amount r={r} />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {!(emphasiseWaiting && r.status === "pending" && !r.amendment_in_progress) && <StatusPill r={r} />}
          {r.category && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-50 px-2 py-0.5 text-[12px] text-zinc-600 ring-1 ring-inset ring-zinc-200">
              <span className={clsx("size-1.5 rounded-full", GROUP[r.category.group].dot)} />
              {r.category.name}
            </span>
          )}
          {r.project && <span className="rounded-full bg-zinc-50 px-2 py-0.5 text-[12px] text-zinc-600 ring-1 ring-inset ring-zinc-200">{r.project.name}</span>}
          {recurring && (
            <span className="inline-flex items-center gap-1 text-[12px] text-zinc-500">
              <Repeat className="size-3" /> {recurring}
            </span>
          )}
          {r.status === "pending" && r.waiting_for && (
            <span className={clsx("inline-flex items-center gap-1 text-[12px]", emphasiseWaiting ? "font-medium text-amber-700" : "text-zinc-500")}>
              <Clock className="size-3" /> {emphasiseWaiting ? `Waiting ${waitingFor(r.waiting_since)}` : `With ${r.waiting_for.name}`}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}

const STEP_STYLE: Record<Step["status"], { ring: string; icon: React.ReactNode; label: string }> = {
  approved: { ring: "bg-emerald-500 text-white", icon: <Check className="size-3.5" strokeWidth={3} />, label: "Approved" },
  rejected: { ring: "bg-rose-500 text-white", icon: <X className="size-3.5" strokeWidth={3} />, label: "Rejected" },
  returned: { ring: "bg-orange-500 text-white", icon: <CornerUpLeft className="size-3.5" strokeWidth={2.5} />, label: "Sent back" },
  pending: { ring: "bg-amber-100 text-amber-700 ring-2 ring-amber-400", icon: <Clock className="size-3.5" strokeWidth={2.5} />, label: "Waiting" },
  waiting: { ring: "bg-zinc-100 text-zinc-400 ring-1 ring-zinc-200", icon: <span className="size-1.5 rounded-full bg-current" />, label: "Next" },
  skipped: { ring: "bg-zinc-100 text-zinc-300 ring-1 ring-zinc-200", icon: <span className="size-1.5 rounded-full bg-current" />, label: "Not needed" },
};

export function ApprovalRoute({ steps, revision, status }: { steps: Step[]; revision: number; status: string }) {
  const current = steps.filter((s) => s.revision === revision);
  if (current.length === 0) {
    return <p className="text-[13px] text-zinc-500">{status === "draft" ? "Approvers are worked out when you submit." : "No approval was needed for this change (within tolerance)."}</p>;
  }
  return (
    <ol className="relative space-y-4">
      {current.map((s, i) => {
        const style = STEP_STYLE[s.status];
        const actor = s.acted_by ?? s.approver;
        return (
          <li key={s.id} className="relative flex gap-3">
            {i < current.length - 1 && <span className="absolute left-[13px] top-8 h-[calc(100%-12px)] w-px bg-zinc-200" />}
            <span className={clsx("relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full", style.ring)}>{style.icon}</span>
            <div className="min-w-0 flex-1 pb-0.5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <p className="text-[14px] font-semibold text-zinc-900">
                  {actor.name}
                  {s.on_behalf_of && <span className="font-normal text-zinc-500"> on behalf of {s.on_behalf_of.name}</span>}
                </p>
                <p className={clsx("text-[12px] font-medium", s.status === "pending" ? "text-amber-700" : "text-zinc-400")}>
                  {s.status === "pending" ? `Waiting ${waitingFor(s.activated_at)}` : s.acted_at ? dateTime(s.acted_at) : style.label}
                </p>
              </div>
              <p className="text-[12.5px] text-zinc-500">{s.reasons.join(" · ")}</p>
              {s.status === "pending" && (
                <p className="mt-1 flex flex-wrap gap-x-3 text-[12px] text-zinc-500">
                  <span>Notified {ago(s.activated_at)}</span>
                  {s.first_viewed_at ? (
                    <span className="inline-flex items-center gap-1">
                      <Eye className="size-3" /> Opened {ago(s.first_viewed_at)}
                    </span>
                  ) : (
                    <span>Not opened yet</span>
                  )}
                  {s.reminder_count > 0 && <span>{s.reminder_count} reminder{s.reminder_count > 1 ? "s" : ""} sent</span>}
                </p>
              )}
              {s.decision_reason && <p className="mt-1.5 text-[13px] font-medium text-rose-700">{s.decision_reason}</p>}
              {s.comment && <p className="mt-1.5 rounded-xl bg-zinc-50 px-3 py-2 text-[13px] leading-relaxed text-zinc-700">“{s.comment}”</p>}
              {s.routing_note && <p className="mt-1.5 text-[12px] italic text-zinc-500">{s.routing_note}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

type Decision = "approve" | "reject" | "return";

export function DecisionDialog({ request, decision, onClose, onDone }: { request: RequestDetail | RequestSummary; decision: Decision | null; onClose: () => void; onDone?: () => void }) {
  const { data: lookups } = useLookups();
  const [reason, setReason] = useState<string>("");
  const [comment, setComment] = useState("");
  const action = useAction(
    (d: Decision) =>
      d === "approve"
        ? api.post(`/api/requests/${request.ref}/approve`, { comment: comment || null })
        : d === "reject"
          ? api.post(`/api/requests/${request.ref}/reject`, { reason, comment: comment || null })
          : api.post(`/api/requests/${request.ref}/return`, { comment }),
    {
      success: decision === "approve" ? "Approved" : decision === "reject" ? "Rejected. The requester has been told why." : "Sent back with your note",
      invalidate: [["dashboard"], ["requests"], ["me"], ["request", request.ref], ["notifications"]],
      onSuccess: () => {
        setReason("");
        setComment("");
        onClose();
        onDone?.();
      },
    },
  );
  if (!decision) return null;
  const titles = { approve: "Approve this request?", reject: "Reject this request", return: "Send back for changes" };
  const canSubmit = decision === "approve" || (decision === "reject" ? !!reason : comment.trim().length > 0);
  return (
    <Modal
      open
      onClose={onClose}
      title={titles[decision]}
      description={
        <>
          {request.title} · <strong className="font-semibold text-zinc-700">{money(request.total_amount, request.currency)}</strong>
          {request.currency !== "USD" && <> (≈ {usd(request.total_usd)})</>} · {request.requester.name}
        </>
      }
      footer={
        <>
          <Button className="flex-1 sm:flex-none" onClick={onClose}>
            Cancel
          </Button>
          <Button
            className="flex-1"
            variant={decision === "reject" ? "danger" : "primary"}
            loading={action.isPending}
            disabled={!canSubmit}
            onClick={() => action.mutate(decision)}
            icon={decision === "approve" ? <Check className="size-4" /> : decision === "reject" ? <X className="size-4" /> : <CornerUpLeft className="size-4" />}
            data-autofocus
          >
            {decision === "approve" ? "Approve" : decision === "reject" ? "Reject" : "Send back"}
          </Button>
        </>
      }
    >
      {decision === "reject" && (
        <div className="mb-4">
          <p className="mb-2 text-[13px] font-medium text-zinc-800">Reason</p>
          <div className="flex flex-wrap gap-2">
            {(lookups?.policy.rejection_reasons ?? []).map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setReason(r)}
                className={clsx("rounded-full px-3 py-1.5 text-[13px] font-medium ring-1 ring-inset transition", reason === r ? "bg-rose-600 text-white ring-rose-600" : "bg-white text-zinc-700 ring-zinc-200 hover:bg-zinc-50")}
              >
                {r}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[12px] text-zinc-500">A reason is required so they don't just submit it again.</p>
        </div>
      )}
      <Field label={decision === "return" ? "What needs to change?" : "Note for the requester"} optional={decision !== "return"}>
        <Textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder={decision === "return" ? "e.g. Please attach the updated quote" : decision === "reject" ? "Anything else they should know" : "Optional"} />
      </Field>
      {"waiting_reasons" in request && request.waiting_reasons.length > 0 && decision === "approve" && (
        <p className="mt-3 flex items-start gap-2 text-[12.5px] text-zinc-500">
          <UserCheck className="mt-px size-4 shrink-0" /> You're approving as: {request.waiting_reasons.join(", ")}.
        </p>
      )}
    </Modal>
  );
}

export function QuickDecision({ r }: { r: RequestSummary }) {
  const [decision, setDecision] = useState<Decision | null>(null);
  return (
    <>
      <div className="flex gap-2 px-4 pb-3.5 sm:px-5">
        <Button size="sm" variant="primary" icon={<Check className="size-3.5" />} onClick={() => setDecision("approve")}>
          Approve
        </Button>
        <Button size="sm" variant="danger" onClick={() => setDecision("reject")}>
          Reject
        </Button>
        {!r.has_quote && r.no_quote_reason && (
          <span className="ml-auto inline-flex items-center gap-1 self-center text-[12px] text-amber-700">
            <Paperclip className="size-3" /> No quote
          </span>
        )}
      </div>
      <DecisionDialog request={r} decision={decision} onClose={() => setDecision(null)} />
    </>
  );
}

export function HBars({ rows, valueKey = "committed_usd", max, labelWidth = "w-32" }: { rows: { label: string; value: number; sub?: string; href?: string; tone?: string }[]; valueKey?: string; max?: number; labelWidth?: string }) {
  const top = max ?? Math.max(1, ...rows.map((r) => r.value));
  void valueKey;
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => {
        const inner = (
          <>
            <span className={clsx("shrink-0 truncate text-[13px] text-zinc-700", labelWidth)}>{r.label}</span>
            <span className="relative h-6 flex-1 overflow-hidden rounded-md bg-zinc-100">
              <span className={clsx("absolute inset-y-0 left-0 rounded-md", r.tone ?? "bg-brand-500/85")} style={{ width: `${Math.max(1.5, (r.value / top) * 100)}%` }} />
            </span>
            <span className="w-20 shrink-0 text-right text-[13px] font-semibold tabular text-zinc-900">{usd(r.value, r.value >= 100000)}</span>
          </>
        );
        return (
          <li key={r.label}>
            {r.href ? (
              <Link to={r.href} className="flex items-center gap-3 rounded-lg hover:opacity-80">
                {inner}
              </Link>
            ) : (
              <div className="flex items-center gap-3">{inner}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function TrendChart({ data }: { data: { month: string; it: number; travel: number; general: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.it + d.travel + d.general));
  return (
    <div>
      <div className="flex h-40 items-end gap-1.5 sm:gap-2.5 lg:h-64">
        {data.map((d) => {
          const total = d.it + d.travel + d.general;
          const label = new Date(`${d.month}-01T12:00:00`).toLocaleDateString("en-GB", { month: "short" });
          return (
            <div key={d.month} className="group flex h-full flex-1 flex-col items-center justify-end gap-1.5">
              <div className="relative flex w-full max-w-9 flex-1 flex-col justify-end overflow-hidden rounded-md">
                <div className="pointer-events-none absolute inset-x-0 -top-0 z-10 hidden whitespace-nowrap text-center text-[11px] font-semibold tabular text-zinc-700 group-hover:block">{usd(total, true)}</div>
                <div className="bg-amber-400" style={{ height: `${(d.general / max) * 100}%` }} />
                <div className="bg-sky-400" style={{ height: `${(d.travel / max) * 100}%` }} />
                <div className="bg-indigo-500" style={{ height: `${(d.it / max) * 100}%` }} />
              </div>
              <span className="text-[11px] text-zinc-500">{label}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex gap-4 text-[12px] text-zinc-500">
        {(["it", "travel", "general"] as const).map((g) => (
          <span key={g} className="inline-flex items-center gap-1.5">
            <span className={clsx("size-2.5 rounded-sm", GROUP[g].bar)} /> {GROUP[g].label}
          </span>
        ))}
      </div>
    </div>
  );
}
