import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { CheckCircle2, Download, ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { api, qs } from "../api/client";
import type { AuditEvent } from "../api/types";
import { Button, Card, ErrorNote, Input, PageHeader, PageLoader, Select } from "../components/ui";
import { dateTime } from "../lib/format";

const ACTIONS = [
  { value: "", label: "All actions" },
  { value: "request.", label: "Requests" },
  { value: "step.", label: "Approval steps" },
  { value: "amendment.", label: "Changes after approval" },
  { value: "invoice.", label: "Invoices & payments" },
  { value: "delegation.", label: "Cover / delegation" },
  { value: "policy.", label: "Approval rules" },
  { value: "user.", label: "People & roles" },
  { value: "auth.", label: "Sign-ins" },
];

export default function Audit() {
  const [f, setF] = useState({ q: "", action: "", ref: "", date_from: "", date_to: "" });
  const [applied, setApplied] = useState(f);
  const [limit, setLimit] = useState(100);
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ["audit", applied, limit],
    queryFn: () => api.get<{ items: AuditEvent[]; total: number }>(`/api/audit${qs({ ...applied, limit })}`),
    placeholderData: (prev) => prev,
  });
  const verify = useQuery({ queryKey: ["audit-verify"], queryFn: () => api.get<{ ok: boolean; events_checked: number; first_bad_event_id: number | null; problem: string | null }>("/api/audit/verify"), enabled: false });

  return (
    <div>
      <PageHeader
        title="Audit log"
        subtitle="Append-only and hash-chained: every event includes a fingerprint of the one before it, so edits or deletions are detectable. The database also refuses to change it."
        actions={
          <>
            <Button icon={<ShieldCheck className="size-4" />} loading={verify.isFetching} onClick={() => verify.refetch()}>
              Verify integrity
            </Button>
            <a href={`/api/audit/export.csv${qs(applied)}`} className="inline-flex h-10 items-center gap-2 rounded-xl bg-white px-4 text-sm font-medium shadow-card ring-1 ring-inset ring-zinc-200 hover:bg-zinc-50">
              <Download className="size-4" /> Export CSV
            </a>
          </>
        }
      />
      {verify.data && (
        <div className={clsx("mb-4 flex items-center gap-3 rounded-2xl px-4 py-3 text-[13.5px] ring-1 ring-inset", verify.data.ok ? "bg-emerald-50 text-emerald-900 ring-emerald-200" : "bg-rose-50 text-rose-900 ring-rose-200")}>
          {verify.data.ok ? <CheckCircle2 className="size-5" /> : <ShieldAlert className="size-5" />}
          {verify.data.ok ? `All ${verify.data.events_checked.toLocaleString()} events verified. The chain is intact.` : `Problem at event ${verify.data.first_bad_event_id}: ${verify.data.problem}`}
        </div>
      )}
      <Card className="mb-4">
        <form
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[2fr_1.3fr_1fr_1fr_1fr_auto]"
          onSubmit={(e) => {
            e.preventDefault();
            setApplied(f);
            setLimit(100);
          }}
        >
          <Input value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} placeholder="Search, e.g. a name or supplier" />
          <Select value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })}>
            {ACTIONS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </Select>
          <Input value={f.ref} onChange={(e) => setF({ ...f, ref: e.target.value })} placeholder="AC-1042" />
          <Input type="date" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} aria-label="From" />
          <Input type="date" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} aria-label="To" />
          <Button type="submit" variant="primary">
            Filter
          </Button>
        </form>
      </Card>
      {isLoading ? (
        <PageLoader />
      ) : error || !data ? (
        <ErrorNote error={error} />
      ) : (
        <Card padded={false} className={clsx(isFetching && "opacity-70")}>
          <p className="border-b border-zinc-100 px-5 py-2.5 text-[12.5px] text-zinc-500">{data.total.toLocaleString()} events</p>
          <ul className="divide-y divide-zinc-100">
            {data.items.map((e) => (
              <li key={e.id} className="grid gap-1 px-4 py-3 sm:grid-cols-[170px_minmax(0,1fr)_auto] sm:gap-4 sm:px-5">
                <span className="text-[12.5px] tabular text-zinc-500">{dateTime(e.occurred_at)}</span>
                <div className="min-w-0">
                  <p className="text-[13.5px] text-zinc-900">{e.summary}</p>
                  <p className="mt-0.5 truncate text-[11.5px] text-zinc-400">
                    {e.action} · #{e.id} · {e.hash.slice(0, 12)}…{e.ip && ` · ${e.ip}`}
                  </p>
                </div>
                {e.request_ref ? (
                  <Link to={`/requests/${e.request_ref}`} className="self-start text-[12.5px] font-medium tabular text-brand-700">
                    {e.request_ref}
                  </Link>
                ) : (
                  <span />
                )}
              </li>
            ))}
          </ul>
          {data.items.length < data.total && (
            <div className="border-t border-zinc-100 p-3 text-center">
              <Button variant="ghost" loading={isFetching} onClick={() => setLimit((l) => l + 100)}>
                Load more
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
