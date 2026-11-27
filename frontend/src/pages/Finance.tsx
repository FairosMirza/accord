import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Download, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { api, qs } from "../api/client";
import type { RequestSummary } from "../api/types";
import { StatusPill } from "../components/requests";
import { Avatar, Card, Empty, ErrorNote, Input, PageHeader, PageLoader, Segmented } from "../components/ui";
import { date, money, usd } from "../lib/format";

type State = "awaiting_invoice" | "awaiting_payment" | "paid" | "all";

export default function Finance() {
  const [state, setState] = useState<State>("awaiting_payment");
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const { data, isLoading, error } = useQuery({
    queryKey: ["finance", state, search],
    queryFn: () => api.get<{ items: RequestSummary[]; totals: Record<string, { count: number; usd: number }> }>(`/api/finance/queue${qs({ state, q: search })}`),
    placeholderData: (prev) => prev,
  });
  const t = data?.totals;
  return (
    <div>
      <PageHeader
        title="Finance"
        subtitle="Everything that's been approved, and whether it's been invoiced and paid. Ask suppliers to quote the AC number on invoices."
        actions={
          <a href="/api/finance/export.csv" className="inline-flex h-10 items-center gap-2 rounded-xl bg-white px-4 text-sm font-medium shadow-card ring-1 ring-inset ring-zinc-200 hover:bg-zinc-50">
            <Download className="size-4" /> Export CSV
          </a>
        }
      />
      <div className="mb-4 grid grid-cols-3 gap-3">
        {(["awaiting_invoice", "awaiting_payment", "paid"] as const).map((k) => (
          <button key={k} type="button" onClick={() => setState(k)} className={clsx("rounded-2xl bg-white p-3.5 text-left shadow-card ring-1 transition sm:p-4", state === k ? "ring-2 ring-brand-500" : "ring-zinc-900/[0.06] hover:ring-zinc-300")}>
            <p className="text-[12px] font-medium text-zinc-500">{{ awaiting_invoice: "Approved, no invoice", awaiting_payment: "Invoiced, not paid", paid: "Paid" }[k]}</p>
            <p className="mt-1 text-[19px] font-semibold tabular tracking-tight sm:text-[22px]">{t ? usd(t[k].usd, t[k].usd > 999999) : "–"}</p>
            <p className="text-[12px] text-zinc-500">{t ? `${t[k].count} requests` : ""}</p>
          </button>
        ))}
      </div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <Segmented
          value={state}
          onChange={setState}
          options={[
            { value: "awaiting_invoice", label: "No invoice" },
            { value: "awaiting_payment", label: "To pay" },
            { value: "paid", label: "Paid" },
            { value: "all", label: "All" },
          ]}
        />
        <form className="relative flex-1" onSubmit={(e) => { e.preventDefault(); setSearch(q); }}>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => setSearch(q)} placeholder="Search by AC number, supplier or title" className="pl-9" />
        </form>
      </div>
      {isLoading ? (
        <PageLoader />
      ) : error || !data ? (
        <ErrorNote error={error} />
      ) : (
        <Card padded={false}>
          {data.items.length === 0 ? (
            <Empty title="Nothing here">All caught up.</Empty>
          ) : (
            <div className="divide-y divide-zinc-100">
              <div className="hidden grid-cols-[minmax(0,1fr)_120px_120px_120px_150px] gap-4 px-5 py-2.5 text-[12px] font-medium uppercase tracking-wide text-zinc-400 md:grid">
                <span>Request</span>
                <span className="text-right">Approved (USD)</span>
                <span className="text-right">Invoiced</span>
                <span className="text-right">Paid</span>
                <span>Status</span>
              </div>
              {data.items.map((r) => (
                <Link key={r.id} to={`/requests/${r.ref}`} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1.5 px-4 py-3 hover:bg-zinc-50 md:grid-cols-[minmax(0,1fr)_120px_120px_120px_150px] md:items-center md:px-5">
                  <div className="flex min-w-0 items-center gap-3">
                    <Avatar name={r.requester.name} initials={r.requester.initials} size="sm" className="hidden sm:inline-flex" />
                    <div className="min-w-0">
                      <p className="truncate text-[14px] font-semibold">{r.title}</p>
                      <p className="truncate text-[12px] text-zinc-500">
                        <span className="tabular">{r.ref}</span> · {r.supplier} · approved {date(r.approved_at, true)}
                      </p>
                    </div>
                  </div>
                  <div className="text-right md:contents">
                    <span className="block text-[14px] font-semibold tabular md:text-right">
                      {usd(r.approved_total_usd)}
                      {r.currency !== "USD" && <span className="block text-[11.5px] font-normal text-zinc-500">{money(r.approved_total_amount, r.currency)}</span>}
                    </span>
                    <span className="hidden text-right text-[13px] tabular text-zinc-600 md:block">{usd(r.finance?.invoiced_usd)}</span>
                    <span className="hidden text-right text-[13px] tabular text-zinc-600 md:block">{usd(r.finance?.paid_usd)}</span>
                  </div>
                  <div className="col-span-2 md:col-span-1">
                    <StatusPill r={r} />
                    {r.finance?.over_approval && <span className="ml-1.5 text-[12px] font-medium text-rose-600">Over approval</span>}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
