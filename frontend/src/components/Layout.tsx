import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  BarChart3,
  Bell,
  CalendarClock,
  Coins,
  FileText,
  FolderKanban,
  Home,
  Inbox,
  Landmark,
  LogOut,
  Mail,
  Menu,
  Plus,
  Scale,
  ScrollText,
  Search,
  Tags,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router";
import { api } from "../api/client";
import { useMe, useNotifications, usePersonas } from "../api/hooks";
import type { Me, UserBrief } from "../api/types";
import { ago, date, ROLE_NAMES } from "../lib/format";
import { useSignOut } from "../lib/session";
import { Logo } from "./Logo";
import { Avatar, ButtonLink, Empty, Input, Modal, PageLoader, Spinner } from "./ui";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  count?: number;
  end?: boolean;
}

function navFor(me: Me): { main: NavItem[]; settings: NavItem[] } {
  const c = me.capabilities;
  const main: NavItem[] = [{ to: "/", label: "Home", icon: <Home className="size-[18px]" />, end: true }];
  if (c.is_approver || me.counts.waiting_for_me > 0) main.push({ to: "/approvals", label: "Approvals", icon: <Inbox className="size-[18px]" />, count: me.counts.waiting_for_me });
  main.push({ to: "/requests", label: "Requests", icon: <FileText className="size-[18px]" /> });
  main.push({ to: "/projects", label: "Projects & trips", icon: <FolderKanban className="size-[18px]" /> });
  if (c.can_view_finance) main.push({ to: "/finance", label: "Finance", icon: <Landmark className="size-[18px]" /> });
  if (c.sees_everything || c.is_manager || c.is_department_head) main.push({ to: "/insights", label: "Insights", icon: <BarChart3 className="size-[18px]" /> });
  if (c.is_approver) main.push({ to: "/cover", label: "Cover while away", icon: <CalendarClock className="size-[18px]" /> });
  const settings: NavItem[] = [{ to: "/settings/policy", label: "Approval rules", icon: <Scale className="size-[18px]" /> }];
  if (c.can_manage_policy || c.can_manage_reference_data) settings.push({ to: "/settings/categories", label: "Categories", icon: <Tags className="size-[18px]" /> });
  if (c.can_manage_reference_data) settings.push({ to: "/settings/rates", label: "Exchange rates", icon: <Coins className="size-[18px]" /> });
  if (c.can_manage_people || c.can_manage_policy) settings.push({ to: "/settings/people", label: "People", icon: <Users className="size-[18px]" /> });
  if (c.can_view_audit) settings.push({ to: "/audit", label: "Audit log", icon: <ScrollText className="size-[18px]" /> });
  if (me.demo_mode) settings.push({ to: "/outbox", label: "Email outbox (demo)", icon: <Mail className="size-[18px]" /> });
  return { main, settings };
}

function SideLink({ item, onClick }: { item: NavItem; onClick?: () => void }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onClick}
      className={({ isActive }) =>
        clsx(
          "group flex items-center gap-3 rounded-xl px-3 py-2 text-[14px] font-medium transition-colors",
          isActive ? "bg-brand-50 text-brand-800" : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900",
        )
      }
    >
      <span className="text-current opacity-80">{item.icon}</span>
      <span className="flex-1 truncate">{item.label}</span>
      {!!item.count && <span className="rounded-full bg-amber-500 px-1.5 py-px text-[11px] font-semibold text-white tabular">{item.count}</span>}
    </NavLink>
  );
}

export function PersonaPicker({ open, onClose, currentId }: { open: boolean; onClose: () => void; currentId?: number }) {
  const { data: personas } = usePersonas(open);
  const [q, setQ] = useState("");
  const [people, setPeople] = useState<UserBrief[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();

  const searching = open && q.trim().length >= 2;
  useEffect(() => {
    if (!searching) return;
    const t = setTimeout(() => api.get<UserBrief[]>(`/api/auth/people?q=${encodeURIComponent(q)}`).then(setPeople).catch(() => setPeople([])), 200);
    return () => clearTimeout(t);
  }, [q, searching]);
  const results = searching ? people : [];

  const signInAs = async (id: number) => {
    setBusy(id);
    try {
      await api.post("/api/auth/demo", { user_id: id });
      qc.clear();
      onClose();
      navigate("/");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Switch person" description="Demo only. In production everyone signs in with their own Microsoft 365 account." wide>
      <div className="grid gap-2 sm:grid-cols-2">
        {(personas ?? []).map((p) => (
          <button
            key={p.user.id}
            type="button"
            onClick={() => signInAs(p.user.id)}
            className={clsx("flex items-start gap-3 rounded-xl p-3 text-left ring-1 ring-inset transition hover:bg-brand-50/60 hover:ring-brand-200", currentId === p.user.id ? "bg-brand-50 ring-brand-300" : "ring-zinc-200")}
          >
            <Avatar name={p.user.name} initials={p.user.initials} />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2 text-[14px] font-semibold text-zinc-900">
                {p.user.name}
                {busy === p.user.id && <Spinner className="size-3.5" />}
              </span>
              <span className="block text-[12px] leading-snug text-zinc-500">{p.headline}</span>
            </span>
          </button>
        ))}
      </div>
      <div className="mt-4">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Or find anyone in the company…" className="pl-9" />
        </div>
        {results.length > 0 && (
          <div className="mt-2 divide-y divide-zinc-100 rounded-xl ring-1 ring-zinc-200">
            {results.map((u) => (
              <button key={u.id} type="button" onClick={() => signInAs(u.id)} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-zinc-50">
                <Avatar name={u.name} initials={u.initials} size="sm" />
                <span className="min-w-0 flex-1 truncate text-[14px]">
                  <span className="font-medium">{u.name}</span> <span className="text-zinc-500">· {u.job_title}</span>
                </span>
                <span className="text-[12px] text-zinc-400">{u.site}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}

function NotificationsButton({ unread }: { unread: number }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useNotifications(open);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const markAll = async () => {
    await api.post("/api/notifications/read", {});
    qc.invalidateQueries({ queryKey: ["notifications"] });
    qc.invalidateQueries({ queryKey: ["me"] });
  };
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="relative rounded-xl p-2 text-zinc-600 hover:bg-zinc-100" aria-label="Notifications">
        <Bell className="size-5" />
        {unread > 0 && <span className="absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-rose-500 text-[10px] font-semibold text-white">{unread > 9 ? "9+" : unread}</span>}
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Notifications"
        description="Everything here was also sent to you by email."
        footer={unread > 0 ? <button type="button" onClick={markAll} className="text-[13px] font-medium text-brand-700">Mark all as read</button> : undefined}
      >
        {isLoading && <PageLoader />}
        {data && data.length === 0 && <Empty title="Nothing yet">You'll hear from Accord when something needs you.</Empty>}
        <ul className="-mx-2 divide-y divide-zinc-100">
          {data?.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                className="flex w-full gap-3 rounded-xl px-2 py-3 text-left hover:bg-zinc-50"
                onClick={async () => {
                  if (!n.read_at) await api.post("/api/notifications/read", { ids: [n.id] }).catch(() => undefined);
                  qc.invalidateQueries({ queryKey: ["me"] });
                  setOpen(false);
                  if (n.link) navigate(n.link);
                }}
              >
                <span className={clsx("mt-1.5 size-2 shrink-0 rounded-full", n.read_at ? "bg-transparent" : "bg-brand-500")} />
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] font-medium leading-snug text-zinc-900">{n.title}</span>
                  {n.body && <span className="mt-0.5 line-clamp-2 block text-[13px] text-zinc-500">{n.body}</span>}
                  <span className="mt-1 block text-[12px] text-zinc-400">{ago(n.created_at)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Modal>
    </>
  );
}

function DemoBar({ me, onSwitch }: { me: Me; onSwitch: () => void }) {
  const roles = me.user.roles.filter((r) => ["coo", "ceo", "finance", "auditor", "admin"].includes(r)).map((r) => ROLE_NAMES[r]);
  return (
    <div className="sticky top-0 z-40 bg-brand-900 text-[12.5px] text-brand-50">
      <div className="flex h-9 items-center gap-2 px-3 sm:px-4">
        <span className="rounded-md bg-white/10 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide">Demo</span>
        <span className="min-w-0 truncate">
          Signed in as <strong className="font-semibold text-white">{me.user.name}</strong>
          <span className="hidden sm:inline">
            , {me.user.job_title}
            {roles.length > 0 && ` · ${roles.join(", ")}`}
          </span>
        </span>
        <button type="button" onClick={onSwitch} className="ml-auto shrink-0 rounded-lg bg-white/15 px-2.5 py-1 font-semibold text-white hover:bg-white/25">
          Switch person
        </button>
      </div>
    </div>
  );
}

export default function Layout() {
  const { data: me, isLoading, error } = useMe();
  const [menuOpen, setMenuOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const signOut = useSignOut();
  const location = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [location.pathname]);
  const nav = useMemo(() => (me ? navFor(me) : null), [me]);

  if (isLoading) return <PageLoader />;
  if (error || !me || !nav) return <Navigate to="/signin" replace />;
  const covering = me.covering.filter((d) => d.state === "active");

  return (
    <div className="min-h-dvh">
      {me.demo_mode && <DemoBar me={me} onSwitch={() => setSwitching(true)} />}
      <aside className={clsx("fixed bottom-0 left-0 z-30 hidden w-64 flex-col border-r border-zinc-200/70 bg-white/70 px-3 pb-4 pt-5 backdrop-blur lg:flex", me.demo_mode ? "top-9" : "top-0")}>
        <Link to="/" className="px-2">
          <Logo />
        </Link>
        <ButtonLink to="/requests/new" variant="primary" className="mx-1 mt-6" icon={<Plus className="size-4" />}>
          New request
        </ButtonLink>
        <nav className="mt-5 flex-1 space-y-0.5 overflow-y-auto">
          {nav.main.map((item) => (
            <SideLink key={item.to} item={item} />
          ))}
          <p className="px-3 pb-1 pt-5 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">Settings & records</p>
          {nav.settings.map((item) => (
            <SideLink key={item.to} item={item} />
          ))}
        </nav>
        <div className="mt-3 flex items-center gap-3 rounded-xl px-2 py-2">
          <Avatar name={me.user.name} initials={me.user.initials} size="sm" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-semibold">{me.user.name}</p>
            <p className="truncate text-[12px] text-zinc-500">{me.user.job_title}</p>
          </div>
          <button type="button" onClick={signOut} className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700" title="Sign out">
            <LogOut className="size-4" />
          </button>
        </div>
      </aside>

      <div className="lg:pl-64">
        <header className={clsx("sticky z-30 flex h-14 items-center gap-2 border-b border-zinc-200/70 bg-canvas/85 px-4 backdrop-blur lg:hidden", me.demo_mode ? "top-9" : "top-0")}>
          <Link to="/">
            <Logo />
          </Link>
          <div className="ml-auto flex items-center gap-1">
            <NotificationsButton unread={me.counts.unread_notifications} />
            <button type="button" onClick={() => setMenuOpen(true)} className="rounded-xl p-1" aria-label="Menu">
              <Avatar name={me.user.name} initials={me.user.initials} size="sm" />
            </button>
          </div>
        </header>
        <div className={clsx("sticky z-20 hidden h-14 items-center justify-end gap-2 px-8 lg:flex", me.demo_mode ? "top-9" : "top-0")}>
          <NotificationsButton unread={me.counts.unread_notifications} />
        </div>

        {covering.length > 0 && (
          <div className="mx-auto max-w-6xl px-4 pt-4 sm:px-6 lg:px-8 lg:pt-0">
            <div className="flex items-center gap-3 rounded-2xl bg-sky-50 px-4 py-3 text-[13px] text-sky-900 ring-1 ring-inset ring-sky-200">
              <CalendarClock className="size-4 shrink-0" />
              <span>
                You're covering approvals for <strong>{covering.map((d) => d.principal.name).join(", ")}</strong> until {date(covering[0].ends_on, true)}. Anything you approve for them is recorded as on their behalf.
              </span>
            </div>
          </div>
        )}

        <main className="mx-auto max-w-6xl px-4 pb-28 pt-5 sm:px-6 lg:px-8 lg:pb-12 lg:pt-1">
          <Outlet />
        </main>
      </div>

      <nav data-bottom-nav className="pb-safe fixed inset-x-0 bottom-0 z-30 border-t border-zinc-200 bg-white/95 backdrop-blur lg:hidden">
        <div className="mx-auto grid max-w-md grid-cols-5 items-end px-2 pt-1.5">
          <BottomLink to="/" end icon={<Home className="size-[22px]" />} label="Home" />
          <BottomLink to="/approvals" icon={<Inbox className="size-[22px]" />} label="Approvals" count={me.counts.waiting_for_me} />
          <Link to="/requests/new" className="-mt-5 flex flex-col items-center gap-1" aria-label="New request">
            <span className="flex size-12 items-center justify-center rounded-2xl bg-brand-700 text-white shadow-pop">
              <Plus className="size-6" />
            </span>
            <span className="text-[11px] font-medium text-zinc-600">New</span>
          </Link>
          <BottomLink to="/requests" icon={<FileText className="size-[22px]" />} label="Requests" />
          <button type="button" onClick={() => setMenuOpen(true)} className="flex flex-col items-center gap-1 py-1 text-zinc-500">
            <Menu className="size-[22px]" />
            <span className="text-[11px] font-medium">More</span>
          </button>
        </div>
      </nav>

      <Modal open={menuOpen} onClose={() => setMenuOpen(false)} title={me.user.name} description={`${me.user.job_title ?? ""}${me.user.department ? ` · ${me.user.department}` : ""}`}>
        <div className="space-y-0.5">
          {[...nav.main.slice(1), ...nav.settings].map((item) => (
            <SideLink key={item.to} item={item} onClick={() => setMenuOpen(false)} />
          ))}
          <button type="button" onClick={signOut} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-[14px] font-medium text-zinc-600 hover:bg-zinc-100">
            <LogOut className="size-[18px]" /> Sign out
          </button>
        </div>
      </Modal>
      <PersonaPicker open={switching} onClose={() => setSwitching(false)} currentId={me.user.id} />
    </div>
  );
}

function BottomLink({ to, icon, label, count, end }: { to: string; icon: ReactNode; label: string; count?: number; end?: boolean }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => clsx("relative flex flex-col items-center gap-1 py-1", isActive ? "text-brand-700" : "text-zinc-500")}>
      {icon}
      {!!count && <span className="absolute -top-0.5 left-1/2 ml-2 flex min-w-4 items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-semibold text-white">{count}</span>}
      <span className="text-[11px] font-medium">{label}</span>
    </NavLink>
  );
}
