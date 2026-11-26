import { useQuery } from "@tanstack/react-query";
import { Search, UserMinus, UserPlus } from "lucide-react";
import { useState } from "react";
import { api, qs } from "../../api/client";
import { useAction, useLookups, useMe } from "../../api/hooks";
import type { Person } from "../../api/types";
import { Avatar, Badge, Button, Card, ErrorNote, Field, Input, Modal, PageHeader, PageLoader, Select, Toggle } from "../../components/ui";
import { ROLE_NAMES } from "../../lib/format";

const ROLES = ["admin", "finance", "finance_admin", "auditor", "executive", "coo", "ceo"];

export default function People() {
  const { data: me } = useMe();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [inactive, setInactive] = useState(false);
  const [editing, setEditing] = useState<Person | null>(null);
  const [adding, setAdding] = useState(false);
  const canEdit = !!me?.capabilities.can_manage_people;
  const { data, isLoading, error } = useQuery({ queryKey: ["people", search, inactive], queryFn: () => api.get<Person[]>(`/api/admin/users${qs({ q: search, include_inactive: inactive || undefined })}`), placeholderData: (p) => p });
  return (
    <div>
      <PageHeader
        title="People"
        subtitle="In production this list syncs from Microsoft Entra ID (name, department, manager), so joiners and leavers update themselves. Roles and positions are set here."
        actions={canEdit ? <Button variant="primary" icon={<UserPlus className="size-4" />} onClick={() => setAdding(true)}>Add person</Button> : undefined}
      />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <form className="relative flex-1" onSubmit={(e) => { e.preventDefault(); setSearch(q); }}>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => setSearch(q)} placeholder="Search name, email or job title" className="pl-9" />
        </form>
        <div className="w-56">
          <Toggle checked={inactive} onChange={setInactive} label={<span className="text-[13px]">Include leavers</span>} />
        </div>
      </div>
      {isLoading ? (
        <PageLoader />
      ) : error || !data ? (
        <ErrorNote error={error} />
      ) : (
        <Card padded={false}>
          <p className="border-b border-zinc-100 px-5 py-2.5 text-[12.5px] text-zinc-500">{data.length} people</p>
          <ul className="divide-y divide-zinc-100">
            {data.map((p) => (
              <li key={p.id}>
                <button type="button" disabled={!canEdit} onClick={() => setEditing(p)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left enabled:hover:bg-zinc-50 sm:px-5">
                  <Avatar name={p.name} initials={p.initials} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[14px] font-medium">
                      {p.name} {!p.is_active && <Badge tone="zinc">Left</Badge>}
                    </p>
                    <p className="truncate text-[12.5px] text-zinc-500">
                      {p.job_title} · {p.department} · {p.site}
                      {p.manager && ` · reports to ${p.manager.name}`}
                    </p>
                  </div>
                  <div className="hidden flex-wrap justify-end gap-1 sm:flex">
                    {p.roles.map((r) => (
                      <Badge key={r} tone={r === "coo" || r === "ceo" ? "brand" : "zinc"}>
                        {ROLE_NAMES[r] ?? r}
                      </Badge>
                    ))}
                    {p.direct_reports > 0 && <span className="text-[12px] text-zinc-400">{p.direct_reports} reports</span>}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {editing && <EditPerson person={editing} onClose={() => setEditing(null)} />}
      {adding && <AddPerson onClose={() => setAdding(false)} />}
    </div>
  );
}

function PersonPicker({ value, onChange, exclude }: { value: number | null; onChange: (id: number | null) => void; exclude?: number }) {
  const { data } = useQuery({ queryKey: ["people", "", false], queryFn: () => api.get<Person[]>("/api/admin/users") });
  return (
    <Select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">Nobody</option>
      {(data ?? []).filter((p) => p.id !== exclude).map((p) => (
        <option key={p.id} value={p.id}>
          {p.name} · {p.job_title}
        </option>
      ))}
    </Select>
  );
}

function EditPerson({ person, onClose }: { person: Person; onClose: () => void }) {
  const { data: lookups } = useLookups();
  const [f, setF] = useState({ job_title: person.job_title ?? "", manager_id: person.manager?.id ?? null, department_id: person.department_id, site_id: person.site_id, roles: person.roles });
  const [leaving, setLeaving] = useState(false);
  const inv = [["people"], ["people-all"], ["policy"], ["me"]];
  const save = useAction(() => api.patch(`/api/admin/users/${person.id}`, f), { success: "Saved", invalidate: inv, onSuccess: onClose });
  const deactivate = useAction(() => api.post<{ steps_reassigned: number; reports_moved: number }>(`/api/admin/users/${person.id}/deactivate`), {
    success: (r) => `${person.name} deactivated. ${r.steps_reassigned} approvals and ${r.reports_moved} direct reports moved to their manager.`,
    invalidate: [...inv, ["dashboard"], ["requests"]],
    onSuccess: onClose,
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={person.name}
      description={person.email}
      footer={
        <>
          {person.is_active && (
            <Button variant="danger" icon={<UserMinus className="size-4" />} onClick={() => setLeaving(true)}>
              Leaver
            </Button>
          )}
          <Button className="ml-auto" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)}>
            Save
          </Button>
        </>
      }
    >
      {leaving ? (
        <div className="space-y-3 rounded-xl bg-rose-50 p-4 text-[13px] text-rose-900 ring-1 ring-inset ring-rose-200">
          <p>
            <strong>{person.name}</strong> will no longer be able to sign in. Anything waiting for their approval, and their direct reports, move to {person.manager?.name ?? "the fallback approver"}. Their history stays on the record.
          </p>
          <div className="flex gap-2">
            <Button onClick={() => setLeaving(false)}>Back</Button>
            <Button variant="danger" loading={deactivate.isPending} onClick={() => deactivate.mutate(undefined)}>
              Deactivate {person.name.split(" ")[0]}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <Field label="Job title">
            <Input value={f.job_title} onChange={(e) => setF({ ...f, job_title: e.target.value })} />
          </Field>
          <Field label="Line manager" hint="Their requests go to this person first.">
            <PersonPicker value={f.manager_id} onChange={(id) => setF({ ...f, manager_id: id })} exclude={person.id} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Department">
              <Select value={f.department_id ?? ""} onChange={(e) => setF({ ...f, department_id: e.target.value ? Number(e.target.value) : null })}>
                {lookups?.departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Site">
              <Select value={f.site_id ?? ""} onChange={(e) => setF({ ...f, site_id: e.target.value ? Number(e.target.value) : null })}>
                {lookups?.sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="Roles and positions" hint="COO and CEO are positions the approval rules point at. Finance lead owns the rules.">
            <div className="flex flex-wrap gap-1.5">
              {ROLES.map((r) => {
                const on = f.roles.includes(r);
                return (
                  <button key={r} type="button" onClick={() => setF({ ...f, roles: on ? f.roles.filter((x) => x !== r) : [...f.roles, r] })} className={`rounded-full px-2.5 py-1 text-[12.5px] font-medium ring-1 ring-inset ${on ? "bg-zinc-900 text-white ring-zinc-900" : "bg-white text-zinc-600 ring-zinc-200"}`}>
                    {ROLE_NAMES[r]}
                  </button>
                );
              })}
            </div>
          </Field>
        </div>
      )}
    </Modal>
  );
}

function AddPerson({ onClose }: { onClose: () => void }) {
  const { data: lookups } = useLookups();
  const [f, setF] = useState({ name: "", email: "", job_title: "", manager_id: null as number | null, department_id: lookups?.departments[0]?.id ?? null, site_id: lookups?.sites[0]?.id ?? null });
  const add = useAction(() => api.post("/api/admin/users", f), { success: "Added", invalidate: [["people"], ["people-all"]], onSuccess: onClose });
  return (
    <Modal open onClose={onClose} title="Add a joiner" description="Normally they'd appear automatically from Microsoft Entra ID on their first sign-in." footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" className="flex-1" loading={add.isPending} disabled={!f.name || !f.email} onClick={() => add.mutate(undefined)}>Add</Button></>}>
      <div className="space-y-3">
        <Field label="Full name">
          <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label="Work email">
          <Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        </Field>
        <Field label="Job title">
          <Input value={f.job_title} onChange={(e) => setF({ ...f, job_title: e.target.value })} />
        </Field>
        <Field label="Line manager">
          <PersonPicker value={f.manager_id} onChange={(id) => setF({ ...f, manager_id: id })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Department">
            <Select value={f.department_id ?? ""} onChange={(e) => setF({ ...f, department_id: Number(e.target.value) })}>
              {lookups?.departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Site">
            <Select value={f.site_id ?? ""} onChange={(e) => setF({ ...f, site_id: Number(e.target.value) })}>
              {lookups?.sites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </div>
    </Modal>
  );
}
