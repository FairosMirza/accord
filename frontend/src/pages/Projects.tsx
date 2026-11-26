import clsx from "clsx";
import { CalendarDays, FolderKanban, MapPin, Pencil, Plane, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { api } from "../api/client";
import { useAction, useMe, useProject, useProjects } from "../api/hooks";
import type { Project } from "../api/types";
import { HBars, RequestRow } from "../components/requests";
import { Button, Card, CardHeader, Empty, ErrorNote, Field, Input, Modal, PageHeader, PageLoader, Progress, Segmented, Stat, Toggle } from "../components/ui";
import { date, usd } from "../lib/format";
import { NewTripModal } from "./RequestForm";
import { BackButton } from "./RequestDetail";

function dates(p: Project) {
  if (!p.start_date) return null;
  return p.end_date ? `${date(p.start_date, true)} – ${date(p.end_date)}` : `From ${date(p.start_date)}`;
}

export function Projects() {
  const [kind, setKind] = useState<"project" | "trip">("project");
  const [closed, setClosed] = useState(false);
  const [creating, setCreating] = useState(false);
  const { data: me } = useMe();
  const { data, isLoading, error } = useProjects(kind, closed);
  return (
    <div>
      <PageHeader
        title="Projects & trips"
        subtitle="Tag spend to a project or trip and the full cost adds up here: approved, invoiced and paid."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>New {kind}</Button>}
      />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Segmented value={kind} onChange={setKind} options={[{ value: "project", label: "Projects" }, { value: "trip", label: "Trips" }]} />
        <div className="w-48">
          <Toggle checked={closed} onChange={setClosed} label={<span className="text-[13px]">Include closed</span>} />
        </div>
      </div>
      {isLoading ? (
        <PageLoader />
      ) : error || !data ? (
        <ErrorNote error={error} />
      ) : data.length === 0 ? (
        <Card>
          <Empty icon={kind === "trip" ? <Plane className="size-5" /> : <FolderKanban className="size-5" />} title={`No ${kind}s yet`}>
            Create one so people can tag their spend to it.
          </Empty>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((p) => {
            const over = p.budget_usd !== null && p.committed_usd > p.budget_usd;
            return (
              <Link key={p.id} to={`/projects/${p.id}`} className={clsx("rounded-2xl bg-white p-4 shadow-card ring-1 ring-zinc-900/[0.06] transition hover:-translate-y-px hover:ring-brand-200", !p.is_active && "opacity-70")}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-[15px] font-semibold">{p.name}</p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12px] text-zinc-500">
                      <span className="tabular">{p.code}</span>
                      {p.destination && (
                        <span className="inline-flex items-center gap-0.5">
                          <MapPin className="size-3" />
                          {p.destination}
                        </span>
                      )}
                    </p>
                  </div>
                  {!p.is_active && <span className="rounded-full bg-zinc-100 px-2 py-px text-[11px] font-medium text-zinc-600">Closed</span>}
                </div>
                <p className="mt-4 text-[24px] font-semibold tabular tracking-tight">{usd(p.committed_usd)}</p>
                <p className="text-[12px] text-zinc-500">
                  approved across {p.count} request{p.count === 1 ? "" : "s"}
                  {p.pending_usd > 0 && <span className="text-amber-700"> · {usd(p.pending_usd, true)} in approval</span>}
                </p>
                {p.budget_usd !== null && (
                  <div className="mt-3">
                    <Progress value={p.committed_usd} max={p.budget_usd} over={over} />
                    <p className={clsx("mt-1.5 text-[12px]", over ? "font-medium text-rose-600" : "text-zinc-500")}>
                      {Math.round((p.committed_usd / p.budget_usd) * 100)}% of {usd(p.budget_usd)} budget{over ? ", over budget" : ""}
                    </p>
                  </div>
                )}
                {dates(p) && (
                  <p className="mt-3 inline-flex items-center gap-1 text-[12px] text-zinc-500">
                    <CalendarDays className="size-3" /> {dates(p)}
                  </p>
                )}
              </Link>
            );
          })}
        </div>
      )}
      <NewTripModal open={creating} onClose={() => setCreating(false)} onCreated={() => undefined} canProject={!!me?.capabilities.can_create_projects} />
    </div>
  );
}

export function ProjectDetail() {
  const { id } = useParams();
  const { data: p, isLoading, error } = useProject(id);
  const { data: me } = useMe();
  const [editing, setEditing] = useState(false);
  if (isLoading) return <PageLoader />;
  if (error || !p) return <ErrorNote error={error} />;
  const canEdit = me && (p.owner?.id === me.user.id || me.capabilities.can_manage_policy || me.capabilities.can_manage_people);
  const over = p.budget_usd !== null && p.committed_usd > p.budget_usd;
  return (
    <div className="space-y-5">
      <div>
        <BackButton fallback="/projects" />
        <PageHeader
          title={p.name}
          subtitle={
            <span className="flex flex-wrap gap-x-3">
              <span>{p.kind === "trip" ? "Trip" : "Project"} · {p.code}</span>
              {p.destination && <span>{p.destination}</span>}
              {dates(p) && <span>{dates(p)}</span>}
              {p.owner && <span>Owner: {p.owner.name}</span>}
            </span>
          }
          actions={canEdit ? <Button icon={<Pencil className="size-4" />} onClick={() => setEditing(true)}>Edit</Button> : undefined}
        />
        {p.description && <p className="-mt-2 max-w-3xl text-[14px] text-zinc-600">{p.description}</p>}
      </div>
      <Card>
        <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
          <Stat label="Total approved" value={usd(p.committed_usd)} hint={`${p.count} requests`} />
          <Stat label="In approval" value={usd(p.pending_usd)} tone={p.pending_usd ? "warn" : "default"} />
          <Stat label="Invoiced" value={usd(p.invoiced_usd)} />
          <Stat label="Paid" value={usd(p.paid_usd)} />
        </div>
        {p.budget_usd !== null && (
          <div className="mt-5">
            <div className="mb-1.5 flex justify-between text-[13px]">
              <span className="text-zinc-500">Budget {usd(p.budget_usd)}</span>
              <span className={over ? "font-semibold text-rose-600" : "font-medium"}>{over ? `${usd(p.committed_usd - p.budget_usd)} over` : `${usd(p.budget_usd - p.committed_usd)} left`}</span>
            </div>
            <Progress value={p.committed_usd} max={p.budget_usd} over={over} className="h-2.5" />
          </div>
        )}
      </Card>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="By category" />
          {p.by_category.length ? <HBars rows={p.by_category.map((r) => ({ label: r.label, value: r.committed_usd + r.pending_usd }))} labelWidth="w-40" /> : <p className="text-[13px] text-zinc-500">No spend yet.</p>}
        </Card>
        <Card>
          <CardHeader title="By department" />
          {p.by_department.length ? <HBars rows={p.by_department.map((r) => ({ label: r.label, value: r.committed_usd + r.pending_usd }))} labelWidth="w-40" /> : <p className="text-[13px] text-zinc-500">No spend yet.</p>}
        </Card>
      </div>
      <Card padded={false}>
        <div className="px-4 pb-1 pt-4 sm:px-5">
          <h2 className="text-[15px] font-semibold">Requests</h2>
          <p className="text-[12.5px] text-zinc-500">The ones you're allowed to see. Totals above include all of them.</p>
        </div>
        {p.requests.length === 0 ? (
          <Empty title="No requests tagged yet" />
        ) : (
          <ul className="divide-y divide-zinc-100">
            {p.requests.map((r) => (
              <li key={r.id}>
                <RequestRow r={r} />
              </li>
            ))}
          </ul>
        )}
      </Card>
      {editing && <EditProject p={p} onClose={() => setEditing(false)} />}
    </div>
  );
}

function EditProject({ p, onClose }: { p: Project; onClose: () => void }) {
  const [f, setF] = useState({ name: p.name, description: p.description ?? "", budget_usd: p.budget_usd?.toString() ?? "", destination: p.destination ?? "", start_date: p.start_date ?? "", end_date: p.end_date ?? "", is_active: p.is_active });
  const save = useAction(
    () => api.patch(`/api/projects/${p.id}`, { ...f, budget_usd: f.budget_usd ? f.budget_usd : null, start_date: f.start_date || null, end_date: f.end_date || null, destination: f.destination || null }),
    { success: "Saved", invalidate: [["project", String(p.id)], ["projects"], ["lookups"]], onSuccess: onClose },
  );
  return (
    <Modal open onClose={onClose} title={`Edit ${p.kind}`} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" className="flex-1" loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></>}>
      <div className="space-y-3">
        <Field label="Name">
          <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label="Description" optional>
          <Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
        <Field label="Budget (USD)" optional hint="Shown against approved spend.">
          <Input inputMode="decimal" value={f.budget_usd} onChange={(e) => setF({ ...f, budget_usd: e.target.value.replace(/[^\d.]/g, "") })} />
        </Field>
        {p.kind === "trip" && (
          <Field label="Destination" optional>
            <Input value={f.destination} onChange={(e) => setF({ ...f, destination: e.target.value })} />
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
        <Toggle checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} label="Open for new spend" description="Close it when the project or trip is finished." />
      </div>
    </Modal>
  );
}
