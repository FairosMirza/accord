import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../../api/client";
import { useAction, useMe } from "../../api/hooks";
import { Button, Card, CardHeader, ErrorNote, Field, Input, PageHeader, PageLoader } from "../../components/ui";
import { date } from "../../lib/format";
import { todayIso } from "../../lib/session";

interface Rate {
  id: number;
  currency: string;
  usd_per_unit: number;
  units_per_usd: number;
  effective_date: string;
  source: string;
}

export default function Rates() {
  const { data: me } = useMe();
  const { data, isLoading, error } = useQuery({ queryKey: ["rates"], queryFn: () => api.get<Rate[]>("/api/admin/fx-rates") });
  const [f, setF] = useState(() => ({ currency: "", per_usd: "", effective_date: todayIso() }));
  const add = useAction(() => api.post("/api/admin/fx-rates", { currency: f.currency, usd_per_unit: (1 / Number(f.per_usd)).toFixed(10), effective_date: f.effective_date }), {
    success: "Rate added",
    invalidate: [["rates"], ["lookups"]],
    onSuccess: () => setF({ ...f, currency: "", per_usd: "" }),
  });
  const grouped = useMemo(() => {
    const m = new Map<string, Rate[]>();
    for (const r of data ?? []) m.set(r.currency, [...(m.get(r.currency) ?? []), r]);
    return [...m.entries()];
  }, [data]);
  if (isLoading) return <PageLoader />;
  if (error || !data) return <ErrorNote error={error} />;
  return (
    <div>
      <PageHeader title="Exchange rates" subtitle="Finance's rates, used to turn local-currency requests and invoices into USD for limits and reporting. Each request keeps the rate it was approved at." />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card padded={false}>
          <ul className="divide-y divide-zinc-100">
            {grouped.map(([cur, rows]) => (
              <li key={cur} className="px-4 py-3 sm:px-5">
                <div className="flex items-baseline justify-between">
                  <p className="text-[15px] font-semibold">{cur}</p>
                  <p className="text-[14px] tabular">
                    1 USD = <strong>{rows[0].units_per_usd.toLocaleString("en-US", { maximumFractionDigits: 4 })}</strong> {cur}
                  </p>
                </div>
                <p className="mt-0.5 text-[12px] text-zinc-500">
                  From {date(rows[0].effective_date)}
                  {rows.length > 1 && ` · earlier: ${rows.slice(1, 4).map((r) => `${r.units_per_usd.toLocaleString("en-US", { maximumFractionDigits: 3 })} from ${date(r.effective_date, true)}`).join(", ")}`}
                </p>
              </li>
            ))}
          </ul>
        </Card>
        {me?.capabilities.can_manage_reference_data && (
          <Card>
            <CardHeader title="Add a rate" subtitle="For a new month or a new currency" />
            <div className="space-y-3">
              <Field label="Currency code">
                <Input value={f.currency} maxLength={3} onChange={(e) => setF({ ...f, currency: e.target.value.toUpperCase() })} placeholder="e.g. KES" />
              </Field>
              <Field label={`1 USD = how many ${f.currency || "units"}?`}>
                <Input inputMode="decimal" value={f.per_usd} onChange={(e) => setF({ ...f, per_usd: e.target.value.replace(/[^\d.]/g, "") })} />
              </Field>
              <Field label="From">
                <Input type="date" value={f.effective_date} onChange={(e) => setF({ ...f, effective_date: e.target.value })} />
              </Field>
              <Button variant="primary" className="w-full" loading={add.isPending} disabled={f.currency.length !== 3 || !Number(f.per_usd)} onClick={() => add.mutate(undefined)}>
                Add rate
              </Button>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
