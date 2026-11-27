import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowDown, ArrowUp, FlaskConical, History, Plus, Scale, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { useAction, useLookups, useMe, usePolicy } from "../../api/hooks";
import type { Group, Person, PolicyDocument, PolicyPayload, PolicyRule, UserBrief } from "../../api/types";
import { Avatar, Button, Card, CardHeader, ErrorNote, Field, Input, Modal, PageHeader, PageLoader, Select, Textarea, Toggle } from "../../components/ui";
import { dateTime, GROUP, usd } from "../../lib/format";

function describe(rule: PolicyRule, labels: Record<string, string>, people: Person[]): string {
  const who =
    rule.approver.type === "line_manager"
      ? "the requester's line manager"
      : rule.approver.type === "department_head"
        ? "the head of their department"
        : rule.approver.type === "role"
          ? `the ${labels[rule.approver.role ?? ""] ?? rule.approver.role}`
          : people.find((p) => p.id === rule.approver.user_id)?.name ?? "a specific person";
  const groups = rule.when.category_groups.length ? rule.when.category_groups.map((g) => GROUP[g].label).join(" or ") + " spend" : "all spend";
  const min = rule.when.min_total_usd !== null && rule.when.min_total_usd !== "" && Number(rule.when.min_total_usd) > 0 ? ` of ${usd(Number(rule.when.min_total_usd))} or more` : "";
  const text = `${groups}${min} is approved by ${who}.`;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export default function Policy() {
  const { data, isLoading, error } = usePolicy();
  if (isLoading) return <PageLoader />;
  if (error || !data) return <ErrorNote error={error} />;
  // Remount the editor when a new version is published, so the draft starts from it.
  return <PolicyEditor key={data.current.version} data={data} />;
}

function PolicyEditor({ data }: { data: PolicyPayload }) {
  const { data: me } = useMe();
  const canEdit = !!me?.capabilities.can_manage_policy;
  const people = useQuery({ queryKey: ["people-all"], queryFn: () => api.get<Person[]>("/api/admin/users"), enabled: canEdit });
  const [doc, setDoc] = useState<PolicyDocument>(() => structuredClone(data.current.document));
  const [publishing, setPublishing] = useState(false);
  const [trying, setTrying] = useState(false);
  const dirty = JSON.stringify(doc) !== JSON.stringify(data.current.document);
  const labels = data.role_labels;
  const positionRoles = Object.keys(data.position_holders);

  const setRule = (i: number, patch: Partial<PolicyRule>) => setDoc({ ...doc, rules: doc.rules.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const move = (i: number, by: number) => {
    const rules = [...doc.rules];
    const [r] = rules.splice(i, 1);
    rules.splice(i + by, 0, r);
    setDoc({ ...doc, rules });
  };
  const addRule = () =>
    setDoc({
      ...doc,
      rules: [...doc.rules, { key: `rule-${Date.now().toString(36)}`, label: "New rule", active: true, approver: { type: "role", role: "coo" }, when: { category_groups: [], category_ids: [], department_ids: [], site_ids: [], min_total_usd: 10000 } }],
    });

  return (
    <div>
      <PageHeader
        title="Approval rules"
        subtitle={`Version ${data.current.version}, published ${dateTime(data.current.created_at)}${data.current.created_by ? ` by ${data.current.created_by.name}` : ""}. Every request records the version that routed it.`}
        actions={
          canEdit ? (
            <>
              <Button icon={<FlaskConical className="size-4" />} onClick={() => setTrying(true)}>
                Try it
              </Button>
              <Button variant="primary" disabled={!dirty} onClick={() => setPublishing(true)}>
                Publish changes
              </Button>
            </>
          ) : undefined
        }
      />
      {!canEdit && <p className="-mt-2 mb-4 text-[13px] text-zinc-500">Finance owns these rules. You can see them so it's clear who approves what.</p>}
      {dirty && <div className="mb-4 rounded-xl bg-amber-50 px-4 py-2.5 text-[13px] text-amber-900 ring-1 ring-inset ring-amber-200">Unpublished changes. Requests already in approval keep the route they started with.</div>}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3">
          <Card>
            <CardHeader title="Approval steps" subtitle="Checked from top to bottom for every request. If the same person comes up twice, they only approve once. Nobody approves their own spend: it goes to their manager instead." icon={<Scale className="size-4" />} />
            <ol className="space-y-3">
              {doc.rules.map((rule, i) => (
                <li key={rule.key} className={clsx("rounded-2xl p-4 ring-1 ring-inset", rule.active ? "ring-zinc-200" : "bg-zinc-50 ring-zinc-200 opacity-70")}>
                  <div className="flex items-start gap-3">
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-[12px] font-semibold text-brand-700">{i + 1}</span>
                    <div className="min-w-0 flex-1 space-y-3">
                      {canEdit ? <Input value={rule.label} onChange={(e) => setRule(i, { label: e.target.value })} className="font-medium" /> : <p className="text-[14.5px] font-semibold">{rule.label}</p>}
                      <p className="text-[13px] text-zinc-600">{describe(rule, labels, people.data ?? [])}</p>
                      {canEdit && (
                        <div className="grid gap-3 sm:grid-cols-3">
                          <Field label="Approver">
                            <Select
                              value={rule.approver.type === "role" ? `role:${rule.approver.role}` : rule.approver.type === "user" ? `user:${rule.approver.user_id}` : rule.approver.type}
                              onChange={(e) => {
                                const v = e.target.value;
                                setRule(i, { approver: v.startsWith("role:") ? { type: "role", role: v.slice(5) } : v.startsWith("user:") ? { type: "user", user_id: Number(v.slice(5)) } : { type: v as "line_manager" | "department_head" } });
                              }}
                            >
                              <option value="line_manager">Line manager</option>
                              <option value="department_head">Department head</option>
                              {positionRoles.map((r) => (
                                <option key={r} value={`role:${r}`}>
                                  {labels[r]}
                                  {data.position_holders[r] ? ` (${data.position_holders[r]?.name})` : ""}
                                </option>
                              ))}
                              <optgroup label="Specific person">
                                {(people.data ?? []).filter((p) => p.direct_reports > 0 || p.roles.length > 0).map((p) => (
                                  <option key={p.id} value={`user:${p.id}`}>
                                    {p.name}
                                  </option>
                                ))}
                              </optgroup>
                            </Select>
                          </Field>
                          <Field label="Applies to">
                            <div className="flex flex-wrap gap-1.5 pt-1">
                              {(["it", "travel", "general"] as Group[]).map((g) => {
                                const on = rule.when.category_groups.includes(g);
                                return (
                                  <button
                                    key={g}
                                    type="button"
                                    onClick={() => setRule(i, { when: { ...rule.when, category_groups: on ? rule.when.category_groups.filter((x) => x !== g) : [...rule.when.category_groups, g] } })}
                                    className={clsx("rounded-full px-2.5 py-1 text-[12.5px] font-medium ring-1 ring-inset", on ? "bg-zinc-900 text-white ring-zinc-900" : "bg-white text-zinc-600 ring-zinc-200")}
                                  >
                                    {GROUP[g].label}
                                  </button>
                                );
                              })}
                            </div>
                          </Field>
                          <Field label="From (USD)" hint="Total commitment">
                            <Input inputMode="decimal" value={rule.when.min_total_usd ?? ""} placeholder="Any amount" onChange={(e) => setRule(i, { when: { ...rule.when, min_total_usd: e.target.value.replace(/[^\d.]/g, "") || null } })} />
                          </Field>
                        </div>
                      )}
                    </div>
                    {canEdit && (
                      <div className="flex shrink-0 flex-col gap-1">
                        <button type="button" disabled={i === 0} onClick={() => move(i, -1)} className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 disabled:opacity-30" aria-label="Move up">
                          <ArrowUp className="size-4" />
                        </button>
                        <button type="button" disabled={i === doc.rules.length - 1} onClick={() => move(i, 1)} className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 disabled:opacity-30" aria-label="Move down">
                          <ArrowDown className="size-4" />
                        </button>
                        <button type="button" onClick={() => setDoc({ ...doc, rules: doc.rules.filter((_, j) => j !== i) })} className="rounded-lg p-1 text-zinc-400 hover:bg-rose-50 hover:text-rose-600" aria-label="Delete rule">
                          <Trash2 className="size-4" />
                        </button>
                      </div>
                    )}
                  </div>
                  {canEdit && (
                    <div className="ml-10 mt-3 w-56">
                      <Toggle checked={rule.active} onChange={(v) => setRule(i, { active: v })} label={<span className="text-[13px]">Active</span>} />
                    </div>
                  )}
                </li>
              ))}
            </ol>
            {canEdit && (
              <Button className="mt-3" variant="ghost" icon={<Plus className="size-4" />} onClick={addRule}>
                Add a rule
              </Button>
            )}
          </Card>
        </div>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Settings" />
            <div className="space-y-3">
              <Field label="Change tolerance after approval (%)" hint="Increases above this go back for approval. Invoices above it need an override.">
                <Input inputMode="decimal" disabled={!canEdit} value={doc.amendment_tolerance_pct} onChange={(e) => setDoc({ ...doc, amendment_tolerance_pct: e.target.value.replace(/[^\d.]/g, "") })} />
              </Field>
              <Field label="Remind approvers after (hours)">
                <Input inputMode="numeric" disabled={!canEdit} value={doc.reminder_after_hours} onChange={(e) => setDoc({ ...doc, reminder_after_hours: Number(e.target.value.replace(/\D/g, "")) || 1 })} />
              </Field>
              <Field label="Rolling contracts are judged on (months)">
                <Input inputMode="numeric" disabled={!canEdit} value={doc.rolling_term_months} onChange={(e) => setDoc({ ...doc, rolling_term_months: Number(e.target.value.replace(/\D/g, "")) || 12 })} />
              </Field>
              <Field label="Renewal reminder (days before end)">
                <Input inputMode="numeric" disabled={!canEdit} value={doc.renewal_notice_days} onChange={(e) => setDoc({ ...doc, renewal_notice_days: Number(e.target.value.replace(/\D/g, "")) || 30 })} />
              </Field>
              <Field label="When nobody else can approve" hint="e.g. the CEO's own requests">
                <Select disabled={!canEdit} value={doc.fallback_approver_role} onChange={(e) => setDoc({ ...doc, fallback_approver_role: e.target.value })}>
                  {positionRoles.map((r) => (
                    <option key={r} value={r}>
                      {labels[r]}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Who can stand in for the COO and CEO">
                <div className="flex flex-wrap gap-1.5">
                  {["ceo", "coo", "finance_admin", "executive"].map((r) => {
                    const on = doc.stand_in_roles.includes(r);
                    return (
                      <button
                        key={r}
                        type="button"
                        disabled={!canEdit}
                        onClick={() => setDoc({ ...doc, stand_in_roles: on ? doc.stand_in_roles.filter((x) => x !== r) : [...doc.stand_in_roles, r] })}
                        className={clsx("rounded-full px-2.5 py-1 text-[12.5px] font-medium ring-1 ring-inset", on ? "bg-zinc-900 text-white ring-zinc-900" : "bg-white text-zinc-600 ring-zinc-200")}
                      >
                        {labels[r] ?? r}
                      </button>
                    );
                  })}
                </div>
              </Field>
              <Field label="Rejection reasons" hint="One per line. Approvers pick one with a single tap.">
                <Textarea disabled={!canEdit} rows={5} value={doc.rejection_reasons.join("\n")} onChange={(e) => setDoc({ ...doc, rejection_reasons: e.target.value.split("\n").map((s) => s.trimStart()).filter((s, i, a) => s || i === a.length - 1) })} />
              </Field>
            </div>
          </Card>
          <Card>
            <CardHeader title="Who holds each position" />
            <ul className="space-y-2.5">
              {Object.entries(data.position_holders).map(([role, u]) => (
                <li key={role} className="flex items-center gap-3 text-[13px]">
                  {u ? <Avatar name={u.name} initials={u.initials} size="sm" /> : <span className="size-7" />}
                  <span className="flex-1">
                    <span className="block font-medium">{labels[role]}</span>
                    <span className="text-zinc-500">{u?.name ?? "Nobody"}</span>
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[12px] text-zinc-500">Rules point at the position, not the person, so when someone changes role the rules keep working. Administrators assign positions under People.</p>
          </Card>
          <Card>
            <CardHeader title="Version history" icon={<History className="size-4" />} />
            <ol className="space-y-3">
              {data.versions.map((v) => (
                <li key={v.version} className="text-[13px]">
                  <p className="font-medium">
                    v{v.version} · {dateTime(v.created_at)}
                  </p>
                  <p className="text-zinc-500">
                    {v.created_by?.name ? `${v.created_by.name}: ` : ""}
                    {v.change_note}
                  </p>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>
      {publishing && <PublishModal doc={doc} onClose={() => setPublishing(false)} />}
      {trying && <TryIt doc={doc} people={people.data ?? []} onClose={() => setTrying(false)} />}
    </div>
  );
}

function cleanDoc(doc: PolicyDocument): PolicyDocument {
  return {
    ...doc,
    rejection_reasons: doc.rejection_reasons.map((r) => r.trim()).filter(Boolean),
    rules: doc.rules.map((r) => ({ ...r, when: { ...r.when, min_total_usd: r.when.min_total_usd === "" || r.when.min_total_usd === null ? null : String(r.when.min_total_usd) } })),
  };
}

function PublishModal({ doc, onClose }: { doc: PolicyDocument; onClose: () => void }) {
  const [note, setNote] = useState("");
  const publish = useAction(() => api.post("/api/admin/policy", { document: cleanDoc(doc), change_note: note }), { success: "Published. New requests use it from now on.", invalidate: [["policy"], ["lookups"]], onSuccess: onClose });
  return (
    <Modal open onClose={onClose} title="Publish new approval rules" description="Requests submitted from now on use the new version. Ones already in approval keep their route. The change is recorded in the audit log." footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" className="flex-1" loading={publish.isPending} disabled={note.trim().length < 3} onClick={() => publish.mutate(undefined)}>Publish</Button></>}>
      <Field label="What changed and why?" hint="e.g. “Authority matrix v1.0 signed off by the board: travel limit USD 2,500”">
        <Textarea value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
    </Modal>
  );
}

function TryIt({ doc, people, onClose }: { doc: PolicyDocument; people: Person[]; onClose: () => void }) {
  const { data: lookups } = useLookups();
  const [f, setF] = useState({ requester_id: "", category_id: "", total_usd: "5000" });
  const [result, setResult] = useState<{ steps: { approver: UserBrief; reasons: string[]; notes: string[] }[] } | null>(null);
  const run = useAction(() => api.post<typeof result>("/api/admin/policy/simulate", { document: cleanDoc(doc), requester_id: Number(f.requester_id), category_id: Number(f.category_id), total_usd: f.total_usd || "0" }), { invalidate: [], onSuccess: setResult });
  return (
    <Modal open onClose={onClose} title="Try the rules" description="See who would approve an example request under the rules as they are on screen, before you publish." wide>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Requester">
          <Select value={f.requester_id} onChange={(e) => setF({ ...f, requester_id: e.target.value })}>
            <option value="">Choose…</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · {p.job_title}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Category">
          <Select value={f.category_id} onChange={(e) => setF({ ...f, category_id: e.target.value })}>
            <option value="">Choose…</option>
            {lookups?.categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Total (USD)">
          <Input inputMode="decimal" value={f.total_usd} onChange={(e) => setF({ ...f, total_usd: e.target.value.replace(/[^\d.]/g, "") })} />
        </Field>
      </div>
      <Button className="mt-3" variant="primary" loading={run.isPending} disabled={!f.requester_id || !f.category_id} onClick={() => run.mutate(undefined)}>
        Show the route
      </Button>
      {result && (
        <ol className="mt-4 space-y-3">
          {result.steps.map((s, i) => (
            <li key={s.approver.id} className="flex gap-3">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-[12px] font-semibold text-brand-700">{i + 1}</span>
              <div>
                <p className="text-[14px] font-semibold">{s.approver.name}</p>
                <p className="text-[12.5px] text-zinc-500">{s.reasons.join(" · ")}</p>
                {s.notes.map((n) => (
                  <p key={n} className="text-[12px] text-sky-800">
                    {n}
                  </p>
                ))}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Modal>
  );
}
