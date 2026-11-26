import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Search, ShieldCheck, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api } from "../api/client";
import { useAuthConfig, usePersonas } from "../api/hooks";
import type { UserBrief } from "../api/types";
import { LogoMark } from "../components/Logo";
import { Avatar, Input, Spinner } from "../components/ui";

const ERRORS: Record<string, string> = {
  sso_failed: "Sign-in didn't complete. Please try again.",
  not_registered: "Your account isn't set up in Accord yet. Ask IT to add you.",
};

export default function SignIn() {
  const { data: config } = useAuthConfig();
  const { data: personas } = usePersonas(!!config?.demo_mode);
  const [params] = useSearchParams();
  const [busy, setBusy] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [people, setPeople] = useState<UserBrief[]>([]);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const error = params.get("error");

  useEffect(() => {
    if (q.trim().length < 2) {
      setPeople([]);
      return;
    }
    const t = setTimeout(() => api.get<UserBrief[]>(`/api/auth/people?q=${encodeURIComponent(q)}`).then(setPeople).catch(() => setPeople([])), 200);
    return () => clearTimeout(t);
  }, [q]);

  const signInAs = async (id: number) => {
    setBusy(id);
    try {
      await api.post("/api/auth/demo", { user_id: id });
      qc.clear();
      navigate("/");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="relative overflow-hidden bg-brand-900 px-6 py-10 text-white sm:px-10 lg:flex lg:flex-col lg:justify-between lg:py-12">
        <div className="pointer-events-none absolute -right-24 -top-24 size-96 rounded-full border-[40px] border-white/[0.04]" />
        <div className="pointer-events-none absolute -bottom-32 -left-20 size-[28rem] rounded-full border-[48px] border-brand-300/[0.06]" />
        <div className="relative flex items-center gap-2.5">
          <LogoMark className="size-9" />
          <span className="text-xl font-semibold tracking-tight">Accord</span>
        </div>
        <div className="relative mt-10 lg:mt-0">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
            Agree the spend
            <br />
            before it happens.
          </h1>
          <p className="mt-4 max-w-md text-[15px] leading-relaxed text-brand-100/80">
            Raise a request, get it approved by the right people, and let Finance match it to the invoice. Everyone sees what they should, and every decision is on the record.
          </p>
          <ul className="mt-8 hidden space-y-3 text-[14px] text-brand-50/90 sm:block">
            <li className="flex gap-3">
              <Smartphone className="size-5 shrink-0 text-brand-300" /> Approve from your phone between meetings
            </li>
            <li className="flex gap-3">
              <CheckCircle2 className="size-5 shrink-0 text-brand-300" /> One step per person. Nobody approves twice, or their own spend
            </li>
            <li className="flex gap-3">
              <ShieldCheck className="size-5 shrink-0 text-brand-300" /> A tamper-evident trail of who approved what, and when
            </li>
          </ul>
        </div>
        <p className="relative mt-10 hidden text-[12px] text-brand-100/50 lg:block">Orvane Group · internal system</p>
      </div>

      <div className="px-5 py-8 sm:px-10 lg:overflow-y-auto lg:py-12">
        <div className="mx-auto max-w-2xl">
          {error && <div className="mb-6 rounded-xl bg-rose-50 px-4 py-3 text-[14px] text-rose-700 ring-1 ring-inset ring-rose-200">{ERRORS[error] ?? "Sign-in failed."}</div>}
          <h2 className="text-xl font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 text-[14px] text-zinc-500">Use your normal work account. There's no Accord password.</p>
          {config?.sso_enabled ? (
            <a href="/api/auth/login" className="mt-5 flex h-12 items-center justify-center gap-3 rounded-xl bg-zinc-900 px-5 text-[15px] font-medium text-white hover:bg-zinc-800">
              <MicrosoftIcon /> Sign in with {config.sso_provider}
            </a>
          ) : (
            <div className="mt-5">
              <button type="button" disabled className="flex h-12 w-full items-center justify-center gap-3 rounded-xl bg-zinc-200 px-5 text-[15px] font-medium text-zinc-500">
                <MicrosoftIcon muted /> Sign in with Microsoft
              </button>
              <p className="mt-2 text-[12px] text-zinc-500">Single sign-on switches on once Orvane IT registers Accord in Microsoft Entra ID. The steps are in the README.</p>
            </div>
          )}

          {config?.demo_mode && (
            <section className="mt-10">
              <div className="flex items-center gap-3">
                <h3 className="text-[15px] font-semibold">Try the demo as…</h3>
                <span className="h-px flex-1 bg-zinc-200" />
              </div>
              <p className="mt-1 text-[13px] text-zinc-500">A demo copy of Orvane with about 120 people and eight months of history. Switch person any time from the bar at the top.</p>
              <div className="mt-4 grid gap-2.5 sm:grid-cols-2">
                {(personas ?? []).map((p, i) => (
                  <button
                    key={p.user.id}
                    type="button"
                    onClick={() => signInAs(p.user.id)}
                    className="group flex items-start gap-3 rounded-2xl bg-white p-3.5 text-left shadow-card ring-1 ring-zinc-900/[0.06] transition hover:-translate-y-px hover:ring-brand-300"
                  >
                    <Avatar name={p.user.name} initials={p.user.initials} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="text-[14px] font-semibold text-zinc-900">{p.user.name}</span>
                        {i === 0 && <span className="rounded-full bg-brand-50 px-1.5 py-px text-[11px] font-semibold text-brand-700 ring-1 ring-inset ring-brand-200">Start here</span>}
                        {busy === p.user.id && <Spinner className="size-3.5" />}
                      </span>
                      <span className="mt-0.5 block text-[12.5px] font-medium text-zinc-600">{p.headline}</span>
                      <span className="mt-1 block text-[12px] leading-snug text-zinc-500">{p.blurb}</span>
                    </span>
                    <ArrowRight className="mt-1 size-4 shrink-0 text-zinc-300 transition group-hover:text-brand-600" />
                  </button>
                ))}
              </div>
              <div className="mt-5">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-400" />
                  <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Or sign in as anyone else, e.g. a site technician" className="pl-9" />
                </div>
                {people.length > 0 && (
                  <div className="mt-2 divide-y divide-zinc-100 rounded-xl bg-white ring-1 ring-zinc-200">
                    {people.map((u) => (
                      <button key={u.id} type="button" onClick={() => signInAs(u.id)} className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-zinc-50">
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
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function MicrosoftIcon({ muted }: { muted?: boolean }) {
  const c = muted ? ["#a1a1aa", "#a1a1aa", "#a1a1aa", "#a1a1aa"] : ["#f25022", "#7fba00", "#00a4ef", "#ffb900"];
  return (
    <svg viewBox="0 0 21 21" className="size-5" aria-hidden="true">
      <rect x="1" y="1" width="9" height="9" fill={c[0]} />
      <rect x="11" y="1" width="9" height="9" fill={c[1]} />
      <rect x="1" y="11" width="9" height="9" fill={c[2]} />
      <rect x="11" y="11" width="9" height="9" fill={c[3]} />
    </svg>
  );
}
