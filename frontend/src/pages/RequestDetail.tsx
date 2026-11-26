import clsx from "clsx";
import {
  ArrowLeft,
  Check,
  CircleAlert,
  CornerUpLeft,
  FileText,
  History,
  Lock,
  Paperclip,
  Pencil,
  Receipt,
  Repeat,
  Send,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api/client";
import { useAction, useMe, useRequest } from "../api/hooks";
import type { Change, Invoice, RequestDetail as Detail } from "../api/types";
import { ApprovalRoute, DecisionDialog, StatusPill } from "../components/requests";
import { Avatar, Badge, Button, ButtonLink, Card, CardHeader, ErrorNote, Field, Input, KeyValue, Modal, PageLoader, Progress, Textarea } from "../components/ui";
import { ago, bytes, date, dateTime, GROUP, money, recurringLabel, usd } from "../lib/format";
import { todayIso } from "../lib/session";

export default function RequestDetail() {
  const { ref } = useParams();
  const { data: r, isLoading, error } = useRequest(ref);
  const { data: me } = useMe();
  const [decision, setDecision] = useState<"approve" | "reject" | "return" | null>(null);
  if (isLoading) return <PageLoader />;
  if (error || !r) return <ErrorNote error={error ?? new Error("Not found")} />;
  const p = r.permissions;
  const isMine = me?.user.id === r.requester.id;
  const pendingAmendment = r.amendment_in_progress ? r.revisions[r.revisions.length - 1] : null;
  const recurring = recurringLabel(r);

  return (
    <div className={clsx(p.can_decide && "pb-24 lg:pb-0")}>
      <BackButton />

      {p.can_decide && (
        <div className="mb-4 flex items-start gap-3 rounded-2xl bg-amber-50 px-4 py-3 text-[13.5px] text-amber-900 ring-1 ring-inset ring-amber-200">
          <CircleAlert className="mt-px size-4 shrink-0" />
          <span>
            <strong>Waiting for you</strong>
            {p.acting_for && <> (covering for {p.acting_for})</>}. You're approving as {r.waiting_reasons.join(", ")}.
          </span>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-5">
          <Card>
            <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-zinc-500">
              <span className="font-medium tabular text-zinc-700">{r.ref}</span>
              <StatusPill r={r} />
              {r.is_confidential && (
                <Badge tone="slate">
                  <Lock className="size-3" /> Confidential
                </Badge>
              )}
            </div>
            <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <h1 className="text-[21px] font-semibold leading-snug tracking-tight text-zinc-900 sm:text-[23px]">{r.title}</h1>
                <div className="mt-2 flex items-center gap-2.5">
                  <Avatar name={r.requester.name} initials={r.requester.initials} size="sm" />
                  <p className="text-[13px] text-zinc-600">
                    <span className="font-medium text-zinc-900">{r.requester.name}</span> · {r.requester.job_title}
                    {r.site && <> · {r.site}</>}
                  </p>
                </div>
              </div>
              <div className="sm:text-right">
                <p className="text-[28px] font-semibold tabular leading-none tracking-tight">{money(r.total_amount, r.currency)}</p>
                {r.currency !== "USD" && <p className="mt-1 text-[14px] tabular text-zinc-500">≈ {usd(r.total_usd)} · 1 USD = {(1 / r.fx_rate).toLocaleString("en-US", { maximumFractionDigits: 2 })} {r.currency}</p>}
                {recurring && (
                  <p className="mt-1 inline-flex items-center gap-1 text-[13px] text-zinc-600">
                    <Repeat className="size-3.5" /> {recurring}
                  </p>
                )}
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {r.category && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-50 px-2.5 py-1 text-[12.5px] text-zinc-700 ring-1 ring-inset ring-zinc-200">
                  <span className={clsx("size-1.5 rounded-full", GROUP[r.category.group].dot)} /> {r.category.name}
                </span>
              )}
              {r.project && (
                <Link to={`/projects/${r.project.id}`} className="rounded-full bg-brand-50 px-2.5 py-1 text-[12.5px] font-medium text-brand-800 ring-1 ring-inset ring-brand-200">
                  {r.project.kind === "trip" ? "Trip" : "Project"}: {r.project.name}
                </Link>
              )}
              {r.supplier && <span className="rounded-full bg-zinc-50 px-2.5 py-1 text-[12.5px] text-zinc-700 ring-1 ring-inset ring-zinc-200">{r.supplier}</span>}
            </div>
            {r.description && <p className="mt-4 whitespace-pre-line text-[14.5px] leading-relaxed text-zinc-700">{r.description}</p>}
          </Card>

          {pendingAmendment && <AmendmentCard r={r} changes={pendingAmendment.changes} reason={pendingAmendment.reason} />}

          <Card>
            <CardHeader title="Approval" subtitle={r.policy_version ? `Routed by approval rules v${r.policy_version}` : undefined} />
            <ApprovalRoute steps={r.steps} revision={r.revision} status={r.status} />
            <EarlierRounds r={r} />
          </Card>

          <Documents r={r} />

          {r.approved_total_usd !== null && <FinancePanel r={r} />}

          <Comments r={r} />
        </div>

        <div className="space-y-5">
          <Actions r={r} isMine={isMine} onDecide={setDecision} />
          <Card>
            <CardHeader title="Details" />
            <KeyValue
              items={[
                ["Department", r.department ?? "–"],
                ["Needed by", date(r.needed_by)],
                ...(r.payment_type === "recurring" ? ([["Contract", `${date(r.start_date)} → ${r.contract_end ? date(r.contract_end) : "rolling"}`]] as [ReactNode, ReactNode][]) : []),
                ["Quote", r.has_quote ? "Attached" : r.no_quote_reason ? <span className="text-amber-700">None: {r.no_quote_reason}</span> : "–"],
                ["Submitted", r.submitted_at ? dateTime(r.submitted_at) : "Not yet"],
                ...(r.approved_at ? ([["Approved", dateTime(r.approved_at)]] as [ReactNode, ReactNode][]) : []),
              ]}
            />
          </Card>
          <Activity r={r} />
        </div>
      </div>

      {p.can_decide && (
        <div data-action-bar className="pb-safe fixed inset-x-0 bottom-0 z-40 border-t border-zinc-200 bg-white/95 px-4 pt-3 backdrop-blur lg:hidden">
          <div className="mx-auto flex max-w-md gap-2">
            <Button size="lg" variant="danger" className="flex-1" onClick={() => setDecision("reject")} icon={<X className="size-4" />}>
              Reject
            </Button>
            {p.can_return && (
              <Button size="lg" className="px-3.5" onClick={() => setDecision("return")} aria-label="Send back">
                <CornerUpLeft className="size-4" />
              </Button>
            )}
            <Button size="lg" variant="primary" className="flex-[1.6]" onClick={() => setDecision("approve")} icon={<Check className="size-4" />}>
              Approve
            </Button>
          </div>
        </div>
      )}
      <DecisionDialog request={r} decision={decision} onClose={() => setDecision(null)} />
    </div>
  );
}

export function BackButton({ fallback = "/requests" }: { fallback?: string }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => (window.history.state?.idx > 0 ? navigate(-1) : navigate(fallback))}
      className="mb-3 inline-flex items-center gap-1 text-[13px] font-medium text-zinc-500 hover:text-zinc-800"
    >
      <ArrowLeft className="size-4" /> Back
    </button>
  );
}

function fmtChange(v: unknown): string {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  const n = Number(v);
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(n) && /^-?\d+(\.\d+)?$/.test(v)) return n.toLocaleString("en-US", { minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2 });
  return String(v);
}

function ChangeList({ changes }: { changes: Change[] }) {
  return (
    <ul className="space-y-1.5">
      {changes.map((c) => (
        <li key={c.field} className="flex flex-wrap items-baseline gap-x-2 text-[13.5px]">
          <span className="w-28 shrink-0 text-zinc-500">{c.field}</span>
          {c.from !== null && c.from !== undefined && <span className="tabular text-zinc-500 line-through">{fmtChange(c.from)}</span>}
          <span className="font-semibold tabular text-zinc-900">{fmtChange(c.to)}</span>
        </li>
      ))}
    </ul>
  );
}

function AmendmentCard({ r, changes, reason }: { r: Detail; changes: Change[]; reason: string | null }) {
  return (
    <div className="rounded-2xl bg-amber-50/70 p-4 ring-1 ring-inset ring-amber-200 sm:p-5">
      <p className="flex items-center gap-2 text-[14px] font-semibold text-amber-900">
        <History className="size-4" /> A change to this approved request needs approval
      </p>
      <p className="mt-1 text-[13px] text-amber-900/80">
        Still approved for {money(r.approved_total_amount, r.currency)} until the change is decided. Reason: “{reason}”
      </p>
      <div className="mt-3 rounded-xl bg-white/80 p-3">
        <ChangeList changes={changes} />
      </div>
    </div>
  );
}

function EarlierRounds({ r }: { r: Detail }) {
  const [open, setOpen] = useState(false);
  const earlier = r.revisions.filter((v) => v.number !== r.revision);
  if (earlier.length === 0) return null;
  return (
    <div className="mt-5 border-t border-zinc-100 pt-3">
      <button type="button" onClick={() => setOpen(!open)} className="text-[13px] font-medium text-zinc-600 hover:text-zinc-900">
        {open ? "Hide" : "Show"} earlier versions ({earlier.length})
      </button>
      {open && (
        <div className="mt-3 space-y-4">
          {[...r.revisions].reverse().filter((v) => v.number !== r.revision).map((v) => (
            <div key={v.number} className="rounded-xl bg-zinc-50 p-3">
              <p className="text-[13px] font-semibold text-zinc-800">
                Version {v.number}: {v.kind === "amendment" ? "change" : v.kind} · {v.status}
                <span className="font-normal text-zinc-500"> · {dateTime(v.created_at)}</span>
              </p>
              {v.reason && <p className="mt-1 text-[12.5px] text-zinc-600">“{v.reason}”</p>}
              {v.changes.length > 0 && (
                <div className="mt-2">
                  <ChangeList changes={v.changes} />
                </div>
              )}
              <div className="mt-3">
                <ApprovalRoute steps={r.steps} revision={v.number} status="" />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Documents({ r }: { r: Detail }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<"quote" | "supporting">("quote");
  const upload = useAction(
    (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("kind", kind);
      return api.post(`/api/requests/${r.ref}/attachments`, fd);
    },
    { success: "Document added", invalidate: [["request", r.ref]] },
  );
  const remove = useAction((id: number) => api.del(`/api/requests/${r.ref}/attachments/${id}`), { success: "Removed", invalidate: [["request", r.ref]] });
  const docs = r.attachments.filter((a) => a.kind !== "invoice");
  return (
    <Card>
      <CardHeader
        title="Documents"
        subtitle={r.has_quote ? "Quotes and supporting documents" : r.no_quote_reason ? `No quote: ${r.no_quote_reason}` : undefined}
        action={
          r.permissions.can_upload ? (
            <div className="flex gap-1.5">
              <Button size="sm" icon={<Upload className="size-3.5" />} loading={upload.isPending} onClick={() => { setKind("quote"); fileRef.current?.click(); }}>
                Add quote
              </Button>
              <Button size="sm" variant="ghost" onClick={() => { setKind("supporting"); fileRef.current?.click(); }}>
                Other
              </Button>
            </div>
          ) : undefined
        }
      />
      <input ref={fileRef} type="file" className="hidden" accept=".pdf,.png,.jpg,.jpeg,.heic,.webp,.doc,.docx,.xls,.xlsx,.eml,.msg,.txt,.csv" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
      {docs.length === 0 ? (
        <p className="text-[13px] text-zinc-500">No documents.</p>
      ) : (
        <ul className="space-y-2">
          {docs.map((a) => (
            <li key={a.id} className="flex items-center gap-3 rounded-xl p-2.5 ring-1 ring-inset ring-zinc-200">
              <span className="rounded-lg bg-zinc-100 p-2 text-zinc-500">
                <FileText className="size-4" />
              </span>
              <a href={`/api/attachments/${a.id}`} target="_blank" rel="noreferrer" className="min-w-0 flex-1">
                <p className="truncate text-[13.5px] font-medium text-zinc-900 hover:text-brand-700">{a.filename}</p>
                <p className="text-[12px] text-zinc-500">
                  {a.kind === "quote" ? "Quote" : "Supporting"} · {bytes(a.size_bytes)} · {ago(a.uploaded_at)} · <span title={a.sha256}>SHA-256 {a.sha256.slice(0, 8)}…</span>
                </p>
              </a>
              {r.permissions.can_edit && (
                <button type="button" onClick={() => remove.mutate(a.id)} className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-rose-600" aria-label="Remove">
                  <Trash2 className="size-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function FinancePanel({ r }: { r: Detail }) {
  const [recording, setRecording] = useState(false);
  const [paying, setPaying] = useState<Invoice | null>(null);
  const [closing, setClosing] = useState(false);
  const f = r.finance!;
  const approved = r.approved_total_usd ?? 0;
  return (
    <Card>
      <CardHeader
        title="Invoices and payments"
        subtitle={`Approved ${money(r.approved_total_amount, r.currency)}${r.currency !== "USD" ? ` (≈ ${usd(approved)})` : ""}`}
        action={
          <div className="flex gap-1.5">
            {r.permissions.can_close && (
              <Button size="sm" variant="ghost" onClick={() => setClosing(true)}>
                Close
              </Button>
            )}
            {r.permissions.can_record_invoice && (
              <Button size="sm" variant="primary" icon={<Receipt className="size-3.5" />} onClick={() => setRecording(true)}>
                Record invoice
              </Button>
            )}
          </div>
        }
      />
      <div className="grid grid-cols-3 gap-3 text-[13px]">
        <div>
          <p className="text-zinc-500">Invoiced</p>
          <p className="text-[16px] font-semibold tabular">{usd(f.invoiced_usd)}</p>
        </div>
        <div>
          <p className="text-zinc-500">Paid</p>
          <p className="text-[16px] font-semibold tabular">{usd(f.paid_usd)}</p>
        </div>
        <div>
          <p className="text-zinc-500">Remaining</p>
          <p className={clsx("text-[16px] font-semibold tabular", f.remaining_usd < 0 && "text-rose-600")}>{usd(f.remaining_usd)}</p>
        </div>
      </div>
      <Progress value={f.invoiced_usd} max={approved} over={f.invoiced_usd > approved} className="mt-3" />
      {r.invoices.length > 0 && (
        <ul className="mt-4 divide-y divide-zinc-100">
          {r.invoices.map((inv) => (
            <li key={inv.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="text-[13.5px] font-medium">
                  {inv.invoice_number} <span className="font-normal text-zinc-500">· {date(inv.invoice_date)}</span>
                </p>
                <p className="text-[12px] text-zinc-500">
                  {inv.status === "paid" ? `Paid ${date(inv.paid_on)}${inv.payment_reference ? ` · ${inv.payment_reference}` : ""} by ${inv.paid_by?.name}` : `Recorded by ${inv.received_by?.name}`}
                  {inv.attachments.map((a) => (
                    <a key={a.id} href={`/api/attachments/${a.id}`} target="_blank" rel="noreferrer" className="ml-2 inline-flex items-center gap-0.5 font-medium text-brand-700">
                      <Paperclip className="size-3" /> PDF
                    </a>
                  ))}
                </p>
                {inv.exceeds_approval && <p className="mt-1 text-[12px] font-medium text-rose-700">Over the approved amount. Override: {inv.override_reason}</p>}
              </div>
              <span className="text-[14px] font-semibold tabular">{money(inv.amount, inv.currency)}</span>
              {inv.status === "paid" ? (
                <Badge tone="green">Paid</Badge>
              ) : r.permissions.can_record_invoice ? (
                <Button size="sm" onClick={() => setPaying(inv)}>
                  Mark paid
                </Button>
              ) : (
                <Badge tone="violet">Awaiting payment</Badge>
              )}
            </li>
          ))}
        </ul>
      )}
      {recording && <InvoiceModal r={r} onClose={() => setRecording(false)} />}
      {paying && <PayModal r={r} invoice={paying} onClose={() => setPaying(null)} />}
      {closing && <ReasonModal r={r} kind="close" onClose={() => setClosing(false)} />}
    </Card>
  );
}

function InvoiceModal({ r, onClose }: { r: Detail; onClose: () => void }) {
  const [form, setForm] = useState(() => ({ invoice_number: "", invoice_date: todayIso(), amount: "", currency: r.currency, supplier: r.supplier ?? "", notes: "", override_reason: "" }));
  const [file, setFile] = useState<File | null>(null);
  const [needsOverride, setNeedsOverride] = useState(false);
  const save = useAction(
    () => {
      const fd = new FormData();
      Object.entries(form).forEach(([k, v]) => v && fd.append(k, v));
      if (file) fd.append("file", file);
      return api.post(`/api/requests/${r.ref}/invoices`, fd);
    },
    { success: "Invoice recorded", invalidate: [["request", r.ref], ["dashboard"], ["requests"]], onSuccess: onClose },
  );
  const onSave = () =>
    save.mutateAsync(undefined).catch((e: { code?: string }) => {
      if (e.code === "exceeds_approval") setNeedsOverride(true);
    });
  return (
    <Modal open onClose={onClose} title="Record invoice" description={`Against ${r.ref}. The supplier should quote this reference on the invoice.`} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" className="flex-1" loading={save.isPending} onClick={onSave} disabled={!form.invoice_number || !form.amount}>Record invoice</Button></>}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Invoice number">
            <Input value={form.invoice_number} onChange={(e) => setForm({ ...form, invoice_number: e.target.value })} />
          </Field>
          <Field label="Invoice date">
            <Input type="date" value={form.invoice_date} onChange={(e) => setForm({ ...form, invoice_date: e.target.value })} />
          </Field>
        </div>
        <div className="grid grid-cols-[1fr_96px] gap-3">
          <Field label="Amount">
            <Input inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value.replace(/[^\d.]/g, "") })} />
          </Field>
          <Field label="Currency">
            <Input value={form.currency} maxLength={3} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} />
          </Field>
        </div>
        <Field label="Supplier">
          <Input value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })} />
        </Field>
        <Field label="Invoice file" optional>
          <input type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-[13px] file:mr-3 file:rounded-lg file:border-0 file:bg-zinc-100 file:px-3 file:py-2 file:text-[13px] file:font-medium" />
        </Field>
        {needsOverride && (
          <Field label="Override reason" hint="This invoice takes spend above what was approved. Record why you're accepting it, or ask the requester to submit a change instead.">
            <Textarea value={form.override_reason} onChange={(e) => setForm({ ...form, override_reason: e.target.value })} />
          </Field>
        )}
      </div>
    </Modal>
  );
}

function PayModal({ r, invoice, onClose }: { r: Detail; invoice: Invoice; onClose: () => void }) {
  const [paidOn, setPaidOn] = useState(todayIso);
  const [reference, setReference] = useState("");
  const pay = useAction(() => api.post(`/api/invoices/${invoice.id}/pay`, { paid_on: paidOn, reference: reference || null }), { success: "Marked as paid", invalidate: [["request", r.ref], ["dashboard"], ["requests"]], onSuccess: onClose });
  return (
    <Modal open onClose={onClose} title={`Pay invoice ${invoice.invoice_number}`} description={`${money(invoice.amount, invoice.currency)} to ${invoice.supplier ?? r.supplier}`} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" className="flex-1" loading={pay.isPending} onClick={() => pay.mutate(undefined)}>Mark as paid</Button></>}>
      <div className="space-y-3">
        <Field label="Paid on">
          <Input type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        </Field>
        <Field label="Payment reference" optional>
          <Input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Bank transfer reference" />
        </Field>
      </div>
    </Modal>
  );
}

function ReasonModal({ r, kind, onClose }: { r: Detail; kind: "cancel" | "close" | "withdraw"; onClose: () => void }) {
  const [text, setText] = useState("");
  const navigate = useNavigate();
  const copy = {
    cancel: { title: "Cancel this request?", label: "Why isn't it going ahead?", button: "Cancel request", success: "Cancelled. Finance has been told." },
    close: { title: "Close this request?", label: "Note", button: "Close request", success: "Closed" },
    withdraw: { title: "Withdraw this request?", label: "", button: "Withdraw", success: "Withdrawn" },
  }[kind];
  const run = useAction(
    () => (kind === "cancel" ? api.post(`/api/requests/${r.ref}/cancel`, { reason: text }) : kind === "close" ? api.post(`/api/requests/${r.ref}/close`, { note: text || null }) : api.post(`/api/requests/${r.ref}/withdraw`)),
    { success: copy.success, invalidate: [["request", r.ref], ["dashboard"], ["requests"], ["me"]], onSuccess: () => { onClose(); if (kind === "withdraw") navigate(`/requests/${r.ref}`); } },
  );
  return (
    <Modal open onClose={onClose} title={copy.title} description={kind === "withdraw" ? "Approvers will be told there's nothing for them to do. The record is kept." : kind === "close" ? "No more invoices will be paid against it." : undefined} footer={<><Button onClick={onClose}>Keep it</Button><Button variant={kind === "close" ? "primary" : "danger"} className="flex-1" loading={run.isPending} disabled={kind === "cancel" && !text.trim()} onClick={() => run.mutate(undefined)}>{copy.button}</Button></>}>
      {kind !== "withdraw" && (
        <Field label={copy.label} optional={kind === "close"}>
          <Textarea value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
      )}
    </Modal>
  );
}

function Actions({ r, isMine, onDecide }: { r: Detail; isMine: boolean; onDecide: (d: "approve" | "reject" | "return") => void }) {
  const p = r.permissions;
  const [modal, setModal] = useState<"cancel" | "withdraw" | null>(null);
  const navigate = useNavigate();
  const submit = useAction(() => api.post(`/api/requests/${r.ref}/submit`), { success: "Submitted. Your approver has been notified.", invalidate: [["request", r.ref], ["dashboard"], ["requests"], ["me"]] });
  const del = useAction(() => api.del(`/api/requests/${r.ref}`), { success: "Draft deleted", onSuccess: () => navigate("/requests?scope=mine") });
  const any = p.can_decide || p.can_edit || p.can_submit || p.can_withdraw || p.can_amend || p.can_cancel || p.can_delete;
  if (!any) {
    if (r.status === "pending" && r.waiting_for) {
      return (
        <Card>
          <p className="text-[13px] text-zinc-500">Waiting for</p>
          <div className="mt-2 flex items-center gap-3">
            <Avatar name={r.waiting_for.name} initials={r.waiting_for.initials} />
            <div>
              <p className="text-[14px] font-semibold">{r.waiting_for.name}</p>
              <p className="text-[12.5px] text-zinc-500">{r.waiting_reasons.join(" · ")}</p>
            </div>
          </div>
          {isMine && <p className="mt-3 text-[12.5px] text-zinc-500">They were emailed and will be reminded daily until they act.</p>}
        </Card>
      );
    }
    return null;
  }
  const requesterActions = p.can_edit || p.can_submit || p.can_amend || p.can_withdraw || p.can_cancel || p.can_delete;
  return (
    <Card className={clsx("space-y-2", !requesterActions && "hidden lg:block")}>
      {p.can_decide && (
        <div className="hidden gap-2 lg:grid">
          <Button variant="primary" size="lg" icon={<Check className="size-4" />} onClick={() => onDecide("approve")}>
            Approve
          </Button>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="danger" onClick={() => onDecide("reject")}>
              Reject
            </Button>
            {p.can_return && <Button onClick={() => onDecide("return")}>Send back</Button>}
          </div>
        </div>
      )}
      <div className="grid gap-2">
        {r.status === "returned" && isMine && <p className="rounded-xl bg-orange-50 px-3 py-2 text-[13px] text-orange-900">Changes were requested. Update the request, then submit it again.</p>}
        {p.can_edit && (
          <ButtonLink to={`/requests/${r.ref}/edit`} icon={<Pencil className="size-4" />}>
            Edit
          </ButtonLink>
        )}
        {p.can_submit && (
          <Button variant="primary" icon={<Send className="size-4" />} loading={submit.isPending} onClick={() => submit.mutate(undefined)}>
            Submit for approval
          </Button>
        )}
        {p.can_amend && (
          <ButtonLink to={`/requests/${r.ref}/change`} icon={<History className="size-4" />}>
            Change amount or details
          </ButtonLink>
        )}
        {p.can_withdraw && (
          <Button variant="ghost" onClick={() => setModal("withdraw")}>
            Withdraw request
          </Button>
        )}
        {p.can_cancel && (
          <Button variant="ghost" onClick={() => setModal("cancel")}>
            Not going ahead
          </Button>
        )}
        {p.can_delete && (
          <Button variant="ghost" className="text-rose-600" loading={del.isPending} onClick={() => del.mutate(undefined)}>
            Delete draft
          </Button>
        )}
      </div>
      {modal && <ReasonModal r={r} kind={modal} onClose={() => setModal(null)} />}
    </Card>
  );
}

function Comments({ r }: { r: Detail }) {
  const [body, setBody] = useState("");
  const add = useAction(() => api.post(`/api/requests/${r.ref}/comments`, { body }), { invalidate: [["request", r.ref]], onSuccess: () => setBody("") });
  if (r.status === "draft") return null;
  return (
    <Card>
      <CardHeader title="Comments" subtitle="Questions and answers, kept with the request" />
      {r.comments.length > 0 && (
        <ul className="mb-4 space-y-3">
          {r.comments.map((c) => (
            <li key={c.id} className="flex gap-3">
              <Avatar name={c.author.name} initials={c.author.initials} size="sm" />
              <div className="min-w-0 flex-1 rounded-2xl rounded-tl-md bg-zinc-50 px-3 py-2">
                <p className="text-[12.5px] text-zinc-500">
                  <span className="font-semibold text-zinc-800">{c.author.name}</span> · {ago(c.created_at)}
                </p>
                <p className="mt-0.5 whitespace-pre-line text-[14px] text-zinc-800">{c.body}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
      {r.permissions.can_comment && (
        <div className="flex gap-2">
          <Input value={body} onChange={(e) => setBody(e.target.value)} placeholder="Ask a question or add context" onKeyDown={(e) => e.key === "Enter" && body.trim() && add.mutate(undefined)} />
          <Button variant="primary" disabled={!body.trim()} loading={add.isPending} onClick={() => add.mutate(undefined)} aria-label="Send">
            <Send className="size-4" />
          </Button>
        </div>
      )}
    </Card>
  );
}

function Activity({ r }: { r: Detail }) {
  const [all, setAll] = useState(false);
  const events = [...r.timeline].reverse();
  const shown = all ? events : events.slice(0, 8);
  return (
    <Card>
      <CardHeader title="Activity" subtitle="Every action, from the audit trail" icon={<ShieldCheck className="size-4" />} />
      {events.length === 0 ? (
        <p className="text-[13px] text-zinc-500">Nothing yet. Drafts are private until submitted.</p>
      ) : (
        <ol className="space-y-3">
          {shown.map((e) => (
            <li key={e.id} className="text-[13px]">
              <p className="leading-snug text-zinc-800">{e.summary}</p>
              <p className="mt-0.5 text-[12px] text-zinc-400" title={`Event ${e.id} · hash ${e.hash}`}>
                {dateTime(e.occurred_at)}
              </p>
            </li>
          ))}
        </ol>
      )}
      {events.length > 8 && (
        <button type="button" onClick={() => setAll(!all)} className="mt-3 text-[13px] font-medium text-brand-700">
          {all ? "Show less" : `Show all ${events.length}`}
        </button>
      )}
    </Card>
  );
}
