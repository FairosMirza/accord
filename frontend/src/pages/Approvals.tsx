import { CheckCircle2 } from "lucide-react";
import { useMe, useRequests } from "../api/hooks";
import { QuickDecision, RequestRow } from "../components/requests";
import { Card, Empty, ErrorNote, PageHeader, PageLoader } from "../components/ui";
import { usd } from "../lib/format";

export default function Approvals() {
  const { data: me } = useMe();
  const { data, isLoading, error } = useRequests({ scope: "waiting", limit: 100 });
  if (isLoading) return <PageLoader />;
  if (error || !data) return <ErrorNote error={error} />;
  const items = [...data.items].sort((a, b) => (a.waiting_since ?? "").localeCompare(b.waiting_since ?? ""));
  const total = items.reduce((s, r) => s + r.total_usd, 0);
  const covering = me?.covering.filter((d) => d.state === "active").map((d) => d.principal.name) ?? [];
  return (
    <div>
      <PageHeader
        title="Approvals"
        subtitle={items.length ? `${items.length} waiting · ${usd(total)} in total · oldest first` : "Nothing is waiting for you."}
      />
      {covering.length > 0 && <p className="-mt-3 mb-4 text-[13px] text-sky-800">Includes approvals for {covering.join(", ")} while you're covering.</p>}
      <Card padded={false}>
        {items.length === 0 ? (
          <Empty icon={<CheckCircle2 className="size-5" />} title="All clear">
            When someone needs your approval you'll get an email and it will appear here.
          </Empty>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {items.map((r) => (
              <li key={r.id}>
                <RequestRow r={r} emphasiseWaiting />
                <div className="-mt-1 px-4 pb-1 text-[12.5px] text-zinc-500 sm:px-5 sm:pl-[68px]">
                  {r.waiting_for && r.waiting_for.id !== me?.user.id ? (
                    <span className="font-medium text-sky-700">Covering for {r.waiting_for.name} · </span>
                  ) : null}
                  You're approving as {r.waiting_reasons.join(", ")}
                </div>
                <div className="sm:pl-12">
                  <QuickDecision r={r} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
