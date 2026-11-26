import { CalendarClock, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { useAction, useDelegations, useEligibleStandIns, useMe } from "../api/hooks";
import type { Delegation } from "../api/types";
import { Avatar, Badge, Button, Card, CardHeader, Empty, Field, Input, PageHeader, PageLoader, Select } from "../components/ui";
import { date } from "../lib/format";
import { todayIso } from "../lib/session";

const STATE_TONE = { active: "green", scheduled: "sky", expired: "zinc", ended: "zinc" } as const;

function Row({ d, mine, onEnd }: { d: Delegation; mine?: boolean; onEnd?: () => void }) {
  const person = mine ? d.delegate : d.principal;
  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <Avatar name={person.name} initials={person.initials} size="sm" />
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-medium">
          {mine ? `${person.name} covers you` : `You cover ${person.name}`}
          {!mine && d.principal && d.delegate && null}
        </p>
        <p className="text-[12.5px] text-zinc-500">
          {date(d.starts_on)} – {date(d.ends_on)}
          {d.note && ` · ${d.note}`}
        </p>
      </div>
      <Badge tone={STATE_TONE[d.state]}>{d.state === "active" ? "Active now" : d.state === "scheduled" ? "Scheduled" : d.state === "ended" ? "Ended early" : "Finished"}</Badge>
      {onEnd && (d.state === "active" || d.state === "scheduled") && (
        <Button size="sm" variant="ghost" onClick={onEnd}>
          {d.state === "active" ? "End now" : "Cancel"}
        </Button>
      )}
    </li>
  );
}

export default function Cover() {
  const { data: me } = useMe();
  const { data, isLoading } = useDelegations();
  const { data: eligible } = useEligibleStandIns();
  const [today] = useState(todayIso);
  const [f, setF] = useState({ delegate_id: "", starts_on: today, ends_on: "", note: "" });
  const inv = [["delegations"], ["me"], ["dashboard"], ["requests"]];
  const create = useAction(() => api.post("/api/delegations", { delegate_id: Number(f.delegate_id), starts_on: f.starts_on, ends_on: f.ends_on, note: f.note || null }), {
    success: "Cover set up. They've been told.",
    invalidate: inv,
    onSuccess: () => setF({ delegate_id: "", starts_on: today, ends_on: "", note: "" }),
  });
  const end = useAction((id: number) => api.post(`/api/delegations/${id}/revoke`), { success: "Cover ended", invalidate: inv });
  if (isLoading || !data || !me) return <PageLoader />;

  return (
    <div className="space-y-5">
      <PageHeader title="Cover while you're away" subtitle="So approvals don't stop when you're on a flight or on leave." />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-5">
          <Card>
            <CardHeader title="Set up cover" subtitle="Your approvals go to your stand-in as well as to you. You can still approve things yourself." icon={<CalendarClock className="size-4" />} />
            <div className="space-y-3">
              <Field label="Stand-in" hint={eligible?.rule}>
                <Select value={f.delegate_id} onChange={(e) => setF({ ...f, delegate_id: e.target.value })}>
                  <option value="">Choose someone…</option>
                  {eligible?.people.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} · {u.job_title}
                    </option>
                  ))}
                </Select>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="From">
                  <Input type="date" value={f.starts_on} min={today} onChange={(e) => setF({ ...f, starts_on: e.target.value })} />
                </Field>
                <Field label="Until (inclusive)">
                  <Input type="date" value={f.ends_on} min={f.starts_on} onChange={(e) => setF({ ...f, ends_on: e.target.value })} />
                </Field>
              </div>
              <Field label="Note" optional>
                <Input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="e.g. Travelling to Lima" />
              </Field>
              <Button variant="primary" loading={create.isPending} disabled={!f.delegate_id || !f.ends_on} onClick={() => create.mutate(undefined)}>
                Set up cover
              </Button>
            </div>
          </Card>
          <Card>
            <CardHeader title="Your cover" />
            {data.mine.length === 0 ? (
              <p className="text-[13px] text-zinc-500">None set up.</p>
            ) : (
              <ul className="divide-y divide-zinc-100">
                {data.mine.map((d) => (
                  <Row key={d.id} d={d} mine onEnd={() => end.mutate(d.id)} />
                ))}
              </ul>
            )}
          </Card>
          {data.covering.length > 0 && (
            <Card>
              <CardHeader title="You're covering" />
              <ul className="divide-y divide-zinc-100">
                {data.covering.map((d) => (
                  <Row key={d.id} d={d} />
                ))}
              </ul>
            </Card>
          )}
        </div>
        <div className="space-y-5">
          <Card>
            <CardHeader title="How it works" icon={<ShieldCheck className="size-4" />} />
            <ul className="space-y-2.5 text-[13px] leading-relaxed text-zinc-600">
              <li>Not just anyone: stand-ins for the COO and CEO must be on Finance's approved list. Everyone else's must be a manager themselves.</li>
              <li>Anything your stand-in approves is recorded as “on behalf of” you, with both names, for the auditors.</li>
              <li>Your stand-in can't approve their own requests. Those wait for you.</li>
              <li>Cover is limited to three months at a time.</li>
            </ul>
          </Card>
          {data.all_current && data.all_current.length > 0 && (
            <Card>
              <CardHeader title="All current cover" subtitle="Across the company" />
              {data.all_current.length === 0 ? (
                <Empty title="None" />
              ) : (
                <ul className="space-y-2.5">
                  {data.all_current.map((d) => (
                    <li key={d.id} className="text-[13px]">
                      <span className="font-medium">{d.delegate.name}</span> covers <span className="font-medium">{d.principal.name}</span>
                      <span className="block text-[12px] text-zinc-500">
                        {date(d.starts_on, true)} – {date(d.ends_on, true)} · {d.state}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
