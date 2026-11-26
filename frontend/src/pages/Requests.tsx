import clsx from "clsx";
import { FileText, Plus, Search } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { useLookups, useMe, useRequests, type RequestFilters } from "../api/hooks";
import { RequestRow } from "../components/requests";
import { Button, ButtonLink, Card, Empty, ErrorNote, Input, PageHeader, PageLoader, Segmented, Select } from "../components/ui";
import { usd } from "../lib/format";

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "pending", label: "In approval" },
  { value: "returned", label: "Changes requested" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Not approved" },
  { value: "closed,cancelled,withdrawn", label: "Closed" },
  { value: "draft", label: "Drafts" },
];

const PAGE = 30;

export default function Requests() {
  const { data: me } = useMe();
  const { data: lookups } = useLookups();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [limit, setLimit] = useState(PAGE);
  const wide = !!me && (me.capabilities.sees_everything || me.capabilities.is_manager || me.capabilities.is_department_head);
  const scope = (params.get("scope") as RequestFilters["scope"]) ?? (wide ? "all" : "mine");
  const filters: RequestFilters = {
    scope,
    status: params.get("status") ?? undefined,
    q: params.get("q") ?? undefined,
    category_group: params.get("category_group") ?? undefined,
    department_id: params.get("department_id") ?? undefined,
    project_id: params.get("project_id") ?? undefined,
    limit,
  };
  const { data, isLoading, error, isFetching } = useRequests(filters);

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setLimit(PAGE);
  };

  const total = data?.items.reduce((s, r) => s + (r.approved_total_usd ?? r.total_usd), 0) ?? 0;

  return (
    <div>
      <PageHeader
        title="Requests"
        subtitle={wide ? "Everything you're allowed to see. Confidential requests only show to the people involved." : "Everything you've raised."}
        actions={<ButtonLink to="/requests/new" variant="primary" icon={<Plus className="size-4" />}>New request</ButtonLink>}
      />
      <div className="mb-4 flex flex-col gap-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          {wide && (
            <Segmented
              value={scope ?? "all"}
              onChange={(v) => set("scope", v)}
              options={[
                { value: "all", label: "All I can see" },
                { value: "mine", label: "Mine" },
                { value: "waiting", label: "Waiting for me" },
              ]}
            />
          )}
          <form
            className="relative flex-1"
            onSubmit={(e) => {
              e.preventDefault();
              set("q", q.trim() || null);
            }}
          >
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-400" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => set("q", q.trim() || null)} placeholder="Search title, supplier, person or AC-number" className="pl-9" />
          </form>
        </div>
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s.value}
              type="button"
              onClick={() => set("status", s.value || null)}
              className={clsx(
                "whitespace-nowrap rounded-full px-3 py-1.5 text-[13px] font-medium ring-1 ring-inset transition",
                (params.get("status") ?? "") === s.value ? "bg-zinc-900 text-white ring-zinc-900" : "bg-white text-zinc-600 ring-zinc-200 hover:bg-zinc-50",
              )}
            >
              {s.label}
            </button>
          ))}
          <Select value={params.get("category_group") ?? ""} onChange={(e) => set("category_group", e.target.value || null)} className="!h-8 !w-auto !rounded-full !py-0 !text-[13px]">
            <option value="">All types</option>
            <option value="it">IT</option>
            <option value="travel">Travel</option>
            <option value="general">General</option>
          </Select>
          {wide && lookups && (
            <Select value={params.get("department_id") ?? ""} onChange={(e) => set("department_id", e.target.value || null)} className="!h-8 !w-auto !rounded-full !py-0 !text-[13px]">
              <option value="">All departments</option>
              {lookups.departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </Select>
          )}
          {params.get("project_id") && lookups && (
            <button type="button" onClick={() => set("project_id", null)} className="whitespace-nowrap rounded-full bg-brand-50 px-3 py-1.5 text-[13px] font-medium text-brand-800 ring-1 ring-inset ring-brand-200">
              {lookups.projects.find((p) => String(p.id) === params.get("project_id"))?.name ?? "Project"} ✕
            </button>
          )}
        </div>
      </div>
      {isLoading ? (
        <PageLoader />
      ) : error || !data ? (
        <ErrorNote error={error} />
      ) : (
        <Card padded={false}>
          {data.items.length === 0 ? (
            <Empty icon={<FileText className="size-5" />} title="No requests match">
              Try a different filter or search.
            </Empty>
          ) : (
            <>
              <div className="flex justify-between border-b border-zinc-100 px-4 py-2.5 text-[12.5px] text-zinc-500 sm:px-5">
                <span>
                  {data.total} request{data.total === 1 ? "" : "s"}
                </span>
                <span className="tabular">Showing {usd(total)}</span>
              </div>
              <ul className={clsx("divide-y divide-zinc-100", isFetching && "opacity-70")}>
                {data.items.map((r) => (
                  <li key={r.id}>
                    <RequestRow r={r} showRequester={scope !== "mine"} />
                  </li>
                ))}
              </ul>
              {data.items.length < data.total && (
                <div className="border-t border-zinc-100 p-3 text-center">
                  <Button variant="ghost" loading={isFetching} onClick={() => setLimit((l) => l + PAGE)}>
                    Show more
                  </Button>
                </div>
              )}
            </>
          )}
        </Card>
      )}
    </div>
  );
}
