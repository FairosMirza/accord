import { ArrowRight, CalendarClock, CheckCircle2, Inbox, Plus } from "lucide-react";
import { Link } from "react-router";
import { useDashboard, useMe } from "../api/hooks";
import { HBars, QuickDecision, RequestRow, TrendChart } from "../components/requests";
import { ButtonLink, Card, CardHeader, Empty, ErrorNote, PageLoader, Stat } from "../components/ui";
import { useState } from "react";
import { date, GROUP, plural, usd } from "../lib/format";
import { greeting as greet } from "../lib/session";

const SCOPE_LABEL = { company: "Across Orvane", department: "Your department", team: "Your team", self: "Your requests" };

export default function Home() {
  const { data: me } = useMe();
  const { data, isLoading, error } = useDashboard();
  const [hour] = useState(() => new Date().getHours());
  const greeting = greet(me?.user.name ?? "", hour);
  if (isLoading || !me) return <PageLoader />;
  if (error || !data) return <ErrorNote error={error} />;
  const n = data.numbers;
  const wide = n.scope !== "self";
  const cover = me.my_cover.find((d) => d.state === "active" || d.state === "scheduled");
  const year = Number(n.period.today.slice(0, 4));

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight sm:text-2xl">{greeting}</h1>
          <p className="mt-1 text-[14px] text-zinc-500">
            {data.waiting.length > 0
              ? `${data.waiting.length} request${data.waiting.length > 1 ? "s are" : " is"} waiting for you.`
              : "Nothing is waiting for you right now."}
          </p>
        </div>
        <div className="hidden sm:block">
          <ButtonLink to="/requests/new" variant="primary" icon={<Plus className="size-4" />}>
            New request
          </ButtonLink>
        </div>
      </div>

      {data.waiting.length > 0 && (
        <Card padded={false}>
          <div className="flex items-center justify-between px-4 pb-1 pt-4 sm:px-5">
            <h2 className="flex items-center gap-2 text-[15px] font-semibold">
              <Inbox className="size-4 text-amber-600" /> Waiting for you
            </h2>
            <Link to="/approvals" className="text-[13px] font-medium text-brand-700">
              See all
            </Link>
          </div>
          <ul className="divide-y divide-zinc-100">
            {data.waiting.slice(0, 5).map((r) => (
              <li key={r.id}>
                <RequestRow r={r} emphasiseWaiting />
                <div className="sm:pl-12">
                  <QuickDecision r={r} />
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {cover && (
        <div className="flex items-center gap-3 rounded-2xl bg-white px-4 py-3 text-[13px] text-zinc-700 shadow-card ring-1 ring-zinc-900/[0.06]">
          <CalendarClock className="size-4 shrink-0 text-sky-600" />
          <span className="flex-1">
            <strong>{cover.delegate.name}</strong> {cover.state === "active" ? "is covering" : "will cover"} your approvals from {date(cover.starts_on, true)} to {date(cover.ends_on, true)}.
          </span>
          <Link to="/cover" className="font-medium text-brand-700">
            Manage
          </Link>
        </div>
      )}

      {wide && (
        <>
          <Card>
            <p className="mb-3 text-[12px] font-semibold uppercase tracking-wider text-brand-700">{SCOPE_LABEL[n.scope]}</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-5 lg:grid-cols-5">
              <Stat label="Approved this month" value={usd(n.committed.month_usd, n.committed.month_usd > 999999)} />
              <Stat label="This quarter" value={usd(n.committed.quarter_usd, n.committed.quarter_usd > 999999)} />
              <Stat label={`So far in ${year}`} value={usd(n.committed.year_usd, n.committed.year_usd > 999999)} />
              <Stat label="Being approved" value={usd(n.pending.usd, n.pending.usd > 999999)} hint={`${n.pending.count} request${n.pending.count === 1 ? "" : "s"}`} tone={n.pending.count ? "warn" : "default"} />
              <Stat label="Approved, not yet invoiced" value={usd(n.awaiting_invoice.usd, n.awaiting_invoice.usd > 999999)} hint={plural(n.awaiting_invoice.count, "request")} />
            </div>
          </Card>

          <div className="grid gap-5 lg:grid-cols-5">
            <Card className="lg:col-span-3">
              <CardHeader title="Approved spend by month" subtitle="Last 12 months, in USD" />
              <TrendChart data={n.trend.slice(Math.max(0, Math.min(n.trend.findIndex((m) => m.it + m.travel + m.general > 0), n.trend.length - 6)))} />
            </Card>
            <Card className="lg:col-span-2">
              <CardHeader title={`What we're spending on, ${year}`} subtitle="Approved spend by type" />
              <HBars
                labelWidth="w-16"
                rows={n.by_group.map((g) => ({ label: GROUP[g.key as keyof typeof GROUP]?.label ?? String(g.label), value: g.committed_usd, tone: GROUP[g.key as keyof typeof GROUP]?.bar, href: `/requests?category_group=${g.key}` }))}
              />
              {n.by_department.filter((d) => d.committed_usd > 0).length > 1 && (
                <>
                  <p className="mb-2.5 mt-6 text-[13px] font-semibold text-zinc-900">By department</p>
                  <HBars rows={n.by_department.filter((d) => d.committed_usd > 0).map((d) => ({ label: d.label, value: d.committed_usd, href: d.key ? `/requests?department_id=${d.key}` : undefined }))} />
                </>
              )}
            </Card>
          </div>

          {n.top_projects.length > 0 && (
            <Card>
              <CardHeader title="Projects and trips" subtitle="Total approved spend, all time" action={<Link to="/projects" className="text-[13px] font-medium text-brand-700">All projects</Link>} />
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {n.top_projects.map((p) => {
                  const over = p.budget_usd ? p.committed_usd > p.budget_usd : false;
                  return (
                    <Link key={String(p.key)} to={`/projects/${p.key}`} className="rounded-xl p-3 ring-1 ring-inset ring-zinc-200 transition hover:bg-zinc-50">
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate text-[14px] font-semibold">{p.label}</p>
                        <span className="rounded-full bg-zinc-100 px-2 py-px text-[11px] font-medium text-zinc-600">{p.kind === "trip" ? "Trip" : "Project"}</span>
                      </div>
                      <p className="mt-1 text-[20px] font-semibold tabular tracking-tight">{usd(p.committed_usd)}</p>
                      <p className={over ? "text-[12px] font-medium text-rose-600" : "text-[12px] text-zinc-500"}>
                        {p.budget_usd ? `${Math.round((p.committed_usd / p.budget_usd) * 100)}% of ${usd(p.budget_usd, true)} budget` : plural(p.count, "request")}
                        {p.pending_usd > 0 && ` · ${usd(p.pending_usd, true)} in approval`}
                      </p>
                    </Link>
                  );
                })}
              </div>
            </Card>
          )}
        </>
      )}

      <Card padded={false}>
        <div className="flex items-center justify-between px-4 pb-1 pt-4 sm:px-5">
          <h2 className="text-[15px] font-semibold">Your requests</h2>
          <Link to="/requests?scope=mine" className="flex items-center gap-1 text-[13px] font-medium text-brand-700">
            All of yours <ArrowRight className="size-3.5" />
          </Link>
        </div>
        {data.mine.length === 0 ? (
          <Empty icon={<CheckCircle2 className="size-5" />} title="No requests yet" action={<ButtonLink to="/requests/new" variant="primary" icon={<Plus className="size-4" />}>Raise your first request</ButtonLink>}>
            Before you spend anything, raise it here. It goes to the right people automatically.
          </Empty>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {data.mine.map((r) => (
              <li key={r.id}>
                <RequestRow r={r} showRequester={false} />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
