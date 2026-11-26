import clsx from "clsx";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { useMe, useSpend } from "../api/hooks";
import { Card, ErrorNote, PageHeader, PageLoader, Segmented, Select } from "../components/ui";
import { GROUP, usd } from "../lib/format";

const GROUPINGS = [
  { value: "department", label: "Department" },
  { value: "category", label: "Category" },
  { value: "group", label: "Type" },
  { value: "site", label: "Site" },
  { value: "project", label: "Project / trip" },
  { value: "supplier", label: "Supplier" },
  { value: "month", label: "Month" },
];

function period(p: string): [string | undefined, string | undefined] {
  const now = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  if (p === "month") return [iso(new Date(now.getFullYear(), now.getMonth(), 1)), iso(now)];
  if (p === "quarter") return [iso(new Date(now.getFullYear(), Math.floor(now.getMonth() / 3) * 3, 1)), iso(now)];
  if (p === "year") return [iso(new Date(now.getFullYear(), 0, 1)), iso(now)];
  if (p === "12m") return [iso(new Date(now.getFullYear() - 1, now.getMonth(), now.getDate() + 1)), iso(now)];
  return [undefined, undefined];
}

export default function Insights() {
  const { data: me } = useMe();
  const [groupBy, setGroupBy] = useState("department");
  const [p, setP] = useState("year");
  const [type, setType] = useState("");
  const [from, to] = period(p);
  const { data, isLoading, error, isFetching } = useSpend(groupBy, from, to, { category_group: type || undefined });
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const max = Math.max(1, ...rows.map((r) => r.committed_usd + r.pending_usd));
  const totals = rows.reduce((t, r) => ({ c: t.c + r.committed_usd, p: t.p + r.pending_usd, i: t.i + r.invoiced_usd, d: t.d + r.paid_usd }), { c: 0, p: 0, i: 0, d: 0 });
  const scope = me?.capabilities.sees_everything ? "the whole company" : me?.capabilities.is_department_head ? "your department" : "your team";

  const link = (key: string | number | null) => {
    if (key === null) return undefined;
    if (groupBy === "department") return `/requests?department_id=${key}`;
    if (groupBy === "project") return `/projects/${key}`;
    if (groupBy === "group") return `/requests?category_group=${key}`;
    return undefined;
  };

  return (
    <div>
      <PageHeader title="Insights" subtitle={`Approved spend for ${scope}, by date of approval. Amounts in USD.`} />
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <Segmented value={groupBy} onChange={setGroupBy} options={GROUPINGS} />
        </div>
        <div className="flex gap-2 lg:ml-auto">
          <Select value={p} onChange={(e) => setP(e.target.value)} className="!w-auto">
            <option value="month">This month</option>
            <option value="quarter">This quarter</option>
            <option value="year">This year</option>
            <option value="12m">Last 12 months</option>
            <option value="all">All time</option>
          </Select>
          <Select value={type} onChange={(e) => setType(e.target.value)} className="!w-auto">
            <option value="">All types</option>
            <option value="it">IT only</option>
            <option value="travel">Travel only</option>
            <option value="general">General only</option>
          </Select>
        </div>
      </div>
      {isLoading ? (
        <PageLoader />
      ) : error ? (
        <ErrorNote error={error} />
      ) : (
        <Card padded={false} className={clsx(isFetching && "opacity-70")}>
          <div className="grid grid-cols-2 gap-4 border-b border-zinc-100 p-4 sm:grid-cols-4 sm:p-5">
            {[
              ["Approved", totals.c],
              ["In approval", totals.p],
              ["Invoiced", totals.i],
              ["Paid", totals.d],
            ].map(([label, v]) => (
              <div key={label as string}>
                <p className="text-[12px] font-medium uppercase tracking-wide text-zinc-500">{label}</p>
                <p className="mt-1 text-[20px] font-semibold tabular">{usd(v as number)}</p>
              </div>
            ))}
          </div>
          <ul className="divide-y divide-zinc-100">
            {rows.map((r) => {
              const href = link(r.key);
              const label = groupBy === "group" ? GROUP[r.key as keyof typeof GROUP]?.label ?? r.label : groupBy === "month" ? new Date(`${r.label}-01T12:00:00`).toLocaleDateString("en-GB", { month: "long", year: "numeric" }) : r.label;
              const content = (
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-4 py-3 sm:grid-cols-[220px_minmax(0,1fr)_110px] sm:px-5">
                  <div className="min-w-0">
                    <p className="truncate text-[14px] font-medium">{label}</p>
                    <p className="text-[12px] text-zinc-500">
                      {r.count} request{r.count === 1 ? "" : "s"} · {usd(r.paid_usd, true)} paid
                    </p>
                  </div>
                  <div className="col-span-2 row-start-2 flex h-2.5 overflow-hidden rounded-full bg-zinc-100 sm:col-span-1 sm:row-start-auto">
                    <div className="bg-brand-500" style={{ width: `${(r.committed_usd / max) * 100}%` }} />
                    <div className="bg-amber-300" style={{ width: `${(r.pending_usd / max) * 100}%` }} />
                  </div>
                  <div className="text-right">
                    <p className="text-[14px] font-semibold tabular">{usd(r.committed_usd)}</p>
                    {r.pending_usd > 0 && <p className="text-[12px] tabular text-amber-700">+{usd(r.pending_usd, true)} pending</p>}
                  </div>
                </div>
              );
              return <li key={String(r.key)}>{href ? <Link to={href} className="block hover:bg-zinc-50">{content}</Link> : content}</li>;
            })}
          </ul>
          {rows.length === 0 && <p className="p-6 text-center text-[13px] text-zinc-500">No spend in this period.</p>}
          <div className="flex gap-4 border-t border-zinc-100 px-5 py-3 text-[12px] text-zinc-500">
            <span className="inline-flex items-center gap-1.5">
              <span className="size-2.5 rounded-sm bg-brand-500" /> Approved
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="size-2.5 rounded-sm bg-amber-300" /> In approval now
            </span>
          </div>
        </Card>
      )}
    </div>
  );
}
