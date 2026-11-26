import clsx from "clsx";
import { Camera, Check, FileText, Info, Lock, Plus, Send, Trash2, UserRound } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { api } from "../api/client";
import { useAction, useLookups, useMe, useRequest } from "../api/hooks";
import type { Lookups, RequestDetail, RoutePreview } from "../api/types";
import { Button, Card, CardHeader, ErrorNote, Field, Input, Modal, PageHeader, PageLoader, Segmented, Select, Textarea, Toggle } from "../components/ui";
import { bytes, GROUP, money, usd } from "../lib/format";
import { BackButton } from "./RequestDetail";

interface FormState {
  title: string;
  category_id: string;
  amount: string;
  currency: string;
  payment_type: "one_off" | "recurring";
  billing_period: "monthly" | "quarterly" | "annually";
  term_months: string;
  start_date: string;
  supplier: string;
  description: string;
  project_id: string;
  needed_by: string;
  no_quote: boolean;
  no_quote_reason: string;
  is_confidential: boolean;
}

const EMPTY: FormState = {
  title: "",
  category_id: "",
  amount: "",
  currency: "USD",
  payment_type: "one_off",
  billing_period: "monthly",
  term_months: "12",
  start_date: "",
  supplier: "",
  description: "",
  project_id: "",
  needed_by: "",
  no_quote: false,
  no_quote_reason: "",
  is_confidential: false,
};

function fromRequest(r: RequestDetail): FormState {
  return {
    title: r.title,
    category_id: r.category ? String(r.category.id) : "",
    amount: r.amount ? String(r.amount) : "",
    currency: r.currency,
    payment_type: r.payment_type,
    billing_period: r.billing_period ?? "monthly",
    term_months: r.term_months ? String(r.term_months) : r.payment_type === "recurring" ? "" : "12",
    start_date: r.start_date ?? "",
    supplier: r.supplier ?? "",
    description: r.description ?? "",
    project_id: r.project ? String(r.project.id) : "",
    needed_by: r.needed_by ?? "",
    no_quote: !!r.no_quote_reason,
    no_quote_reason: r.no_quote_reason ?? "",
    is_confidential: r.is_confidential,
  };
}

function toPayload(f: FormState) {
  const recurring = f.payment_type === "recurring";
  return {
    title: f.title.trim(),
    category_id: f.category_id ? Number(f.category_id) : null,
    amount: f.amount ? Number(f.amount).toFixed(2) : "0.00",
    currency: f.currency,
    payment_type: f.payment_type,
    billing_period: recurring ? f.billing_period : null,
    term_months: recurring && f.term_months ? Number(f.term_months) : null,
    start_date: recurring && f.start_date ? f.start_date : null,
    supplier: f.supplier.trim() || null,
    description: f.description.trim() || null,
    project_id: f.project_id ? Number(f.project_id) : null,
    needed_by: f.needed_by || null,
    no_quote_reason: f.no_quote ? f.no_quote_reason.trim() || null : null,
    is_confidential: f.is_confidential,
  };
}

function useRoutePreview(form: FormState) {
  const [preview, setPreview] = useState<RoutePreview | null>(null);
  const [loading, setLoading] = useState(false);
  const key = JSON.stringify([form.category_id, form.amount, form.currency, form.payment_type, form.billing_period, form.term_months]);
  useEffect(() => {
    if (!form.category_id) {
      setPreview(null);
      return;
    }
    setLoading(true);
    const t = setTimeout(() => {
      const p = toPayload(form);
      api
        .post<RoutePreview>("/api/requests/preview", { category_id: p.category_id, amount: p.amount, currency: p.currency, payment_type: p.payment_type, billing_period: p.billing_period, term_months: p.term_months })
        .then(setPreview)
        .catch(() => setPreview(null))
        .finally(() => setLoading(false));
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return { preview, loading };
}

export function RoutePreviewCard({ form, preview, loading, lookups }: { form: FormState; preview: RoutePreview | null; loading: boolean; lookups: Lookups }) {
  const total = Number(preview?.total_amount ?? 0);
  const totalUsd = Number(preview?.total_usd ?? 0);
  const recurring = form.payment_type === "recurring";
  return (
    <Card className="lg:sticky lg:top-20">
      <CardHeader title="Who will approve" subtitle={preview?.policy_version ? `Worked out from approval rules v${preview.policy_version}` : "Pick a category and amount"} />
      {form.category_id && total > 0 && (
        <div className="mb-4 rounded-xl bg-zinc-50 p-3">
          <p className="text-[12px] text-zinc-500">{recurring ? "Total commitment over the term" : "Total"}</p>
          <p className="text-[20px] font-semibold tabular">{money(total, form.currency)}</p>
          {form.currency !== lookups.base_currency && <p className="text-[12.5px] tabular text-zinc-500">≈ {usd(totalUsd)}, which is what the limits use</p>}
          {recurring && <p className="mt-1 text-[12px] text-zinc-500">Recurring costs are approved once, for the whole term.</p>}
        </div>
      )}
      {loading && !preview && <p className="text-[13px] text-zinc-400">Working it out…</p>}
      {preview?.steps.length ? (
        <ol className={clsx("space-y-3", loading && "opacity-60")}>
          {preview.steps.map((s, i) => (
            <li key={s.approver.id} className="flex gap-3">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-[12px] font-semibold text-brand-700 ring-1 ring-inset ring-brand-200">{i + 1}</span>
              <div className="min-w-0">
                <p className="text-[14px] font-semibold">{s.approver.name}</p>
                <p className="text-[12.5px] text-zinc-500">{s.reasons.join(" · ")}</p>
                {s.notes.map((n) => (
                  <p key={n} className="mt-1 flex gap-1 text-[12px] text-sky-800">
                    <Info className="mt-px size-3 shrink-0" /> {n}
                  </p>
                ))}
              </div>
            </li>
          ))}
        </ol>
      ) : (
        !loading && <p className="flex items-center gap-2 text-[13px] text-zinc-500"><UserRound className="size-4" /> Your line manager first, then anyone the rules add.</p>
      )}
      <p className="mt-4 border-t border-zinc-100 pt-3 text-[12px] leading-relaxed text-zinc-500">Nobody approves twice, and nobody approves their own request. Approvers are emailed straight away and reminded each working day.</p>
    </Card>
  );
}

export function NewTripModal({ open, onClose, onCreated, canProject }: { open: boolean; onClose: () => void; onCreated: (id: number) => void; canProject: boolean }) {
  const [kind, setKind] = useState<"trip" | "project">("trip");
  const [f, setF] = useState({ name: "", destination: "", start_date: "", end_date: "" });
  const create = useAction((body: object) => api.post<{ id: number; name: string }>("/api/projects", body), {
    success: (p) => `${p.name} created`,
    invalidate: [["lookups"], ["projects"]],
    onSuccess: (p) => {
      onCreated(p.id);
      onClose();
      setF({ name: "", destination: "", start_date: "", end_date: "" });
    },
  });
  return (
    <Modal open={open} onClose={onClose} title={kind === "trip" ? "New trip" : "New project"} description="Everyone can tag their spend to it, so the total cost is in one place." footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" className="flex-1" loading={create.isPending} disabled={f.name.trim().length < 2} onClick={() => create.mutate({ kind, name: f.name, destination: f.destination || null, start_date: f.start_date || null, end_date: f.end_date || null })}>Create</Button></>}>
      <div className="space-y-3">
        {canProject && <Segmented value={kind} onChange={setKind} options={[{ value: "trip", label: "Trip" }, { value: "project", label: "Project" }]} />}
        <Field label="Name">
          <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder={kind === "trip" ? "e.g. Mining Indaba 2027" : "e.g. New finance system"} />
        </Field>
        {kind === "trip" && (
          <Field label="Destination" optional>
            <Input value={f.destination} onChange={(e) => setF({ ...f, destination: e.target.value })} placeholder="City, country" />
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="From" optional>
            <Input type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} />
          </Field>
          <Field label="To" optional>
            <Input type="date" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} />
          </Field>
        </div>
      </div>
    </Modal>
  );
}

function Section({ title, children, hint }: { title: string; children: ReactNode; hint?: string }) {
  return (
    <Card>
      <CardHeader title={title} subtitle={hint} />
      <div className="space-y-4">{children}</div>
    </Card>
  );
}

export function RequestFields({ form, set, lookups, canCreateProject, amendment }: { form: FormState; set: (patch: Partial<FormState>) => void; lookups: Lookups; canCreateProject: boolean; amendment?: boolean }) {
  const [tripOpen, setTripOpen] = useState(false);
  const category = lookups.categories.find((c) => String(c.id) === form.category_id);
  const grouped = useMemo(() => (["it", "travel", "general"] as const).map((g) => ({ g, items: lookups.categories.filter((c) => c.group === g) })), [lookups]);
  return (
    <>
      <Section title="What is it?">
        <Field label="Short title" hint="What you'd say if someone asked. e.g. “Figma licences for the design team”">
          <Input value={form.title} onChange={(e) => set({ title: e.target.value })} maxLength={200} disabled={amendment} />
        </Field>
        <Field label="Category" hint={category?.description ?? "Finance's categories. IT spend always goes to the COO."}>
          <Select
            value={form.category_id}
            onChange={(e) => {
              const c = lookups.categories.find((x) => String(x.id) === e.target.value);
              set({ category_id: e.target.value, ...(c?.confidential_default ? { is_confidential: true } : {}), ...(c && !c.quote_required ? { no_quote: false } : {}) });
            }}
          >
            <option value="">Choose…</option>
            {grouped.map(({ g, items }) => (
              <optgroup key={g} label={GROUP[g].label}>
                {items.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </Select>
        </Field>
        <Field label="Who are you paying?">
          <Input value={form.supplier} onChange={(e) => set({ supplier: e.target.value })} placeholder="Supplier or organisation" />
        </Field>
        <Field label="Why is it needed?" hint="Approvers decide on this. What is it for, and what happens if we don't?">
          <Textarea value={form.description} onChange={(e) => set({ description: e.target.value })} rows={4} />
        </Field>
      </Section>

      <Section title="How much?">
        <Segmented value={form.payment_type} onChange={(v) => set({ payment_type: v })} options={[{ value: "one_off", label: "One-off" }, { value: "recurring", label: "Subscription or retainer" }]} />
        <div className="grid grid-cols-[1fr_110px] gap-3">
          <Field label={form.payment_type === "recurring" ? "Amount per payment" : "Amount"}>
            <Input inputMode="decimal" value={form.amount} onChange={(e) => set({ amount: e.target.value.replace(/[^\d.]/g, "") })} placeholder="0.00" className="tabular" />
          </Field>
          <Field label="Currency">
            <Select value={form.currency} onChange={(e) => set({ currency: e.target.value })}>
              {lookups.currencies.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </Select>
          </Field>
        </div>
        {form.payment_type === "recurring" && (
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Paid">
              <Select value={form.billing_period} onChange={(e) => set({ billing_period: e.target.value as FormState["billing_period"] })}>
                <option value="monthly">Monthly</option>
                <option value="quarterly">Quarterly</option>
                <option value="annually">Annually</option>
              </Select>
            </Field>
            <Field label="Contract length">
              <Select value={form.term_months} onChange={(e) => set({ term_months: e.target.value })}>
                <option value="3">3 months</option>
                <option value="6">6 months</option>
                <option value="12">1 year</option>
                <option value="24">2 years</option>
                <option value="36">3 years</option>
                <option value="60">5 years</option>
                <option value="">Rolling (no end date)</option>
              </Select>
            </Field>
            <Field label="Starts" optional>
              <Input type="date" value={form.start_date} onChange={(e) => set({ start_date: e.target.value })} />
            </Field>
          </div>
        )}
        {form.payment_type === "recurring" && !form.term_months && <p className="text-[12px] text-zinc-500">Rolling contracts are judged on {lookups.policy.rolling_term_months} months of spend.</p>}
      </Section>

      <Section title="Context">
        <Field label="Project or trip" hint="Tag it so the total cost of a project or trip adds up in one place.">
          <div className="flex gap-2">
            <Select value={form.project_id} onChange={(e) => set({ project_id: e.target.value })}>
              <option value="">Not for a project or trip</option>
              <optgroup label="Projects">
                {lookups.projects.filter((p) => p.kind === "project").map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Trips">
                {lookups.projects.filter((p) => p.kind === "trip").map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </optgroup>
            </Select>
            <Button onClick={() => setTripOpen(true)} icon={<Plus className="size-4" />} aria-label="New trip or project">
              <span className="hidden sm:inline">New</span>
            </Button>
          </div>
        </Field>
        {!amendment && (
          <Field label="Needed by" optional>
            <Input type="date" value={form.needed_by} onChange={(e) => set({ needed_by: e.target.value })} />
          </Field>
        )}
        <Toggle
          checked={form.is_confidential}
          onChange={(v) => set({ is_confidential: v })}
          label={
            <span className="inline-flex items-center gap-1.5">
              <Lock className="size-3.5" /> Confidential
            </span>
          }
          description="Only you, your approvers, Finance and executives can see it. Use for legal, HR or other sensitive spend."
        />
      </Section>
      <NewTripModal open={tripOpen} onClose={() => setTripOpen(false)} onCreated={(id) => set({ project_id: String(id) })} canProject={canCreateProject} />
    </>
  );
}

function QuoteSection({ form, set, files, setFiles, existing, quoteRequired }: { form: FormState; set: (p: Partial<FormState>) => void; files: File[]; setFiles: (f: File[]) => void; existing: number; quoteRequired: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <Section title="Quote" hint={quoteRequired ? "Attach the supplier's quote, so approvers and Finance know what was agreed." : "Not required for this category, but attach one if you have it."}>
      <input ref={input} type="file" multiple className="hidden" accept=".pdf,.png,.jpg,.jpeg,.heic,.webp,.doc,.docx,.xls,.xlsx,.eml,.msg" onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? [])]); e.target.value = ""; }} />
      {!form.no_quote && (
        <button type="button" onClick={() => input.current?.click()} className="flex w-full flex-col items-center gap-1.5 rounded-2xl border-2 border-dashed border-zinc-200 px-4 py-6 text-center transition hover:border-brand-300 hover:bg-brand-50/40">
          <span className="rounded-xl bg-brand-50 p-2.5 text-brand-700">
            <Camera className="size-5" />
          </span>
          <span className="text-[14px] font-medium text-zinc-800">Add a quote</span>
          <span className="text-[12px] text-zinc-500">PDF, photo, Word, Excel or a forwarded email · up to 15 MB</span>
        </button>
      )}
      {(files.length > 0 || existing > 0) && (
        <ul className="space-y-2">
          {existing > 0 && <li className="text-[13px] text-zinc-500">{existing} document{existing > 1 ? "s" : ""} already attached</li>}
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-3 rounded-xl p-2.5 ring-1 ring-inset ring-zinc-200">
              <FileText className="size-4 text-zinc-400" />
              <span className="min-w-0 flex-1 truncate text-[13.5px]">{f.name}</span>
              <span className="text-[12px] text-zinc-400">{bytes(f.size)}</span>
              <button type="button" onClick={() => setFiles(files.filter((_, j) => j !== i))} className="rounded-lg p-1 text-zinc-400 hover:text-rose-600" aria-label="Remove">
                <Trash2 className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {quoteRequired && (
        <>
          <Toggle checked={form.no_quote} onChange={(v) => set({ no_quote: v })} label="There's no quote for this" description="For example a visa fee or a fixed government charge." />
          {form.no_quote && (
            <Field label="Why not?">
              <Input value={form.no_quote_reason} onChange={(e) => set({ no_quote_reason: e.target.value })} placeholder="e.g. Fixed government fee" />
            </Field>
          )}
        </>
      )}
    </Section>
  );
}

async function uploadAll(ref: string, files: File[]) {
  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f);
    fd.append("kind", "quote");
    await api.post(`/api/requests/${ref}/attachments`, fd);
  }
}

export default function RequestForm() {
  const { ref } = useParams();
  const editing = !!ref;
  const { data: existing, isLoading } = useRequest(ref);
  const { data: lookups } = useLookups();
  const { data: me } = useMe();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState<"draft" | "submit" | null>(null);
  const navigate = useNavigate();
  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }));
  const { preview, loading } = useRoutePreview(form);

  useEffect(() => {
    if (existing) setForm(fromRequest(existing));
    else if (lookups && !editing) setForm((f) => ({ ...f, currency: lookups.default_currency === "AED" ? "USD" : lookups.default_currency }));
  }, [existing, lookups, editing]);

  if ((editing && isLoading) || !lookups || !me) return <PageLoader />;
  if (editing && existing && !existing.permissions.can_edit) return <ErrorNote error={new Error("This request can't be edited now. Approved requests can be changed with 'Change amount or details'.")} />;
  const category = lookups.categories.find((c) => String(c.id) === form.category_id);
  const quoteRequired = category?.quote_required ?? true;
  const existingDocs = existing?.attachments.filter((a) => a.kind !== "invoice").length ?? 0;

  const save = async (submit: boolean) => {
    setBusy(submit ? "submit" : "draft");
    let savedRef = ref;
    try {
      const payload = toPayload(form);
      const saved = editing ? await api.patch<RequestDetail>(`/api/requests/${ref}`, payload) : await api.post<RequestDetail>("/api/requests", payload);
      savedRef = saved.ref;
      await uploadAll(saved.ref, files);
      setFiles([]);
      if (submit) {
        await api.post(`/api/requests/${saved.ref}/submit`);
        toast.success("Submitted. Your approver has been emailed.");
      } else {
        toast.success("Draft saved");
      }
      navigate(`/requests/${saved.ref}`, { replace: true });
    } catch (e) {
      toast.error((e as Error).message);
      if (!editing && savedRef) navigate(`/requests/${savedRef}/edit`, { replace: true });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <BackButton />
      <PageHeader
        title={editing ? (existing?.status === "returned" ? "Update and resubmit" : "Edit draft") : "New spend request"}
        subtitle={editing && existing?.status === "returned" ? "Your approver asked for changes. Make them below and submit again." : "Raise it before you commit to anything. It goes to the right people automatically."}
      />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-5">
          <RequestFields form={form} set={set} lookups={lookups} canCreateProject={me.capabilities.can_create_projects} />
          <QuoteSection form={form} set={set} files={files} setFiles={setFiles} existing={existingDocs} quoteRequired={quoteRequired} />
        </div>
        <div className="space-y-4">
          <RoutePreviewCard form={form} preview={preview} loading={loading} lookups={lookups} />
          <div data-action-bar className="pb-safe fixed inset-x-0 bottom-0 z-40 flex gap-2 border-t border-zinc-200 bg-white/95 px-4 pt-3 backdrop-blur lg:static lg:border-0 lg:bg-transparent lg:p-0">
            <Button size="lg" className="flex-1" loading={busy === "draft"} disabled={!!busy || !form.title.trim()} onClick={() => save(false)}>
              Save draft
            </Button>
            <Button size="lg" variant="primary" className="flex-[1.5]" loading={busy === "submit"} disabled={!!busy || !form.title.trim()} onClick={() => save(true)} icon={<Send className="size-4" />}>
              Submit
            </Button>
          </div>
        </div>
      </div>
      <div className="h-20 lg:hidden" />
    </div>
  );
}

export function AmendForm() {
  const { ref } = useParams();
  const { data: r, isLoading } = useRequest(ref);
  const { data: lookups } = useLookups();
  const { data: me } = useMe();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [reason, setReason] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }));
  const { preview, loading } = useRoutePreview(form);
  useEffect(() => {
    if (r) setForm(fromRequest(r));
  }, [r]);
  if (isLoading || !r || !lookups || !me) return <PageLoader />;
  if (!r.permissions.can_amend) return <ErrorNote error={new Error("Only the requester can change an approved request.")} />;

  const save = async () => {
    setBusy(true);
    try {
      await uploadAll(r.ref, files);
      const p = toPayload(form);
      const result = await api.post<RequestDetail>(`/api/requests/${r.ref}/amend`, {
        reason,
        amount: p.amount,
        currency: p.currency,
        payment_type: p.payment_type,
        billing_period: p.billing_period,
        term_months: p.term_months,
        start_date: p.start_date,
        supplier: p.supplier,
        description: p.description,
        project_id: p.project_id,
        category_id: p.category_id,
        is_confidential: p.is_confidential,
      });
      toast.success(result.amendment?.needs_reapproval ? "Sent for approval. The original approval stands until then." : "Change recorded. Finance has been told.", { description: result.amendment?.explanation });
      navigate(`/requests/${r.ref}`, { replace: true });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const tolerance = lookups.policy.amendment_tolerance_pct;
  return (
    <div>
      <BackButton />
      <PageHeader title="Change an approved request" subtitle={`${r.ref} · ${r.title} · approved for ${money(r.approved_total_amount, r.currency)}`} />
      <div className="mb-5 flex gap-3 rounded-2xl bg-sky-50 px-4 py-3 text-[13px] leading-relaxed text-sky-900 ring-1 ring-inset ring-sky-200">
        <Info className="mt-0.5 size-4 shrink-0" />
        <span>
          Approvals can't be edited, but quotes change. If the total goes up by more than {tolerance}%, or the change needs someone new to approve it, it goes back for approval and the original approval stands meanwhile. Smaller changes are recorded and Finance is told.
        </span>
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-5">
          <RequestFields form={form} set={set} lookups={lookups} canCreateProject={me.capabilities.can_create_projects} amendment />
          <Section title="Why is it changing?">
            <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Supplier's revised quote after the site survey" />
          </Section>
          <QuoteSection form={{ ...form, no_quote: false }} set={() => undefined} files={files} setFiles={setFiles} existing={0} quoteRequired={false} />
        </div>
        <div className="space-y-4">
          <RoutePreviewCard form={form} preview={preview} loading={loading} lookups={lookups} />
          <Button size="lg" variant="primary" className="w-full" loading={busy} disabled={!reason.trim()} onClick={save} icon={<Check className="size-4" />}>
            Submit change
          </Button>
        </div>
      </div>
    </div>
  );
}
