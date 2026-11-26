import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Mail, RotateCcw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, qs } from "../api/client";
import { useMe } from "../api/hooks";
import type { OutboxEmail } from "../api/types";
import { Avatar, Button, Card, Empty, ErrorNote, Modal, PageHeader, PageLoader, Toggle } from "../components/ui";
import { ago } from "../lib/format";

export default function Outbox() {
  const { data: me } = useMe();
  const [mineOnly, setMineOnly] = useState(true);
  const [open, setOpen] = useState<number | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [busy, setBusy] = useState<"reminders" | "reset" | null>(null);
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["outbox", mineOnly, me?.user.id],
    queryFn: () => api.get<OutboxEmail[]>(`/api/demo/outbox${qs({ to_user_id: mineOnly ? me?.user.id : undefined })}`),
    enabled: !!me,
  });
  const message = useQuery({ queryKey: ["outbox-msg", open], queryFn: () => api.get<{ subject: string; body_html: string }>(`/api/demo/outbox/${open}`), enabled: open !== null });

  const runReminders = async () => {
    setBusy("reminders");
    try {
      const r = await api.post<{ reminders: number; renewals: number; skipped_weekend: boolean }>("/api/demo/run-reminders");
      toast.success(r.skipped_weekend ? "It's the weekend in Dubai, so no approval reminders were sent." : `Sent ${r.reminders} approval reminder${r.reminders === 1 ? "" : "s"}`, { description: `${r.renewals} contract renewal notice${r.renewals === 1 ? "" : "s"}` });
      qc.invalidateQueries();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const reset = async () => {
    setBusy("reset");
    try {
      await api.post("/api/demo/reset");
      qc.clear();
      window.location.href = "/signin";
    } catch (e) {
      toast.error((e as Error).message);
      setBusy(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Email outbox"
        subtitle="Demo only. The demo people don't have real inboxes, so here's every email Accord sent. In production these go out through Microsoft 365."
        actions={
          <>
            <Button icon={<BellRing className="size-4" />} loading={busy === "reminders"} onClick={runReminders}>
              Run reminder job now
            </Button>
            <Button variant="danger" icon={<RotateCcw className="size-4" />} onClick={() => setConfirmReset(true)}>
              Reset demo data
            </Button>
          </>
        }
      />
      <div className="mb-4 w-64">
        <Toggle checked={mineOnly} onChange={setMineOnly} label={<span className="text-[13px]">Only emails to {me?.user.name.split(" ")[0]}</span>} />
      </div>
      {isLoading ? (
        <PageLoader />
      ) : error || !data ? (
        <ErrorNote error={error} />
      ) : (
        <Card padded={false}>
          {data.length === 0 ? (
            <Empty icon={<Mail className="size-5" />} title="No emails" />
          ) : (
            <ul className="divide-y divide-zinc-100">
              {data.map((e) => (
                <li key={e.id}>
                  <button type="button" onClick={() => setOpen(e.id)} className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-zinc-50 sm:px-5">
                    <Avatar name={e.to?.name ?? e.to_email} initials={e.to?.initials} size="sm" />
                    <div className="min-w-0 flex-1">
                      <p className="flex justify-between gap-3 text-[13px] text-zinc-500">
                        <span className="truncate">To {e.to?.name ?? e.to_email}</span>
                        <span className="shrink-0">{ago(e.created_at)}</span>
                      </p>
                      <p className="truncate text-[14px] font-medium">{e.subject}</p>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
      <Modal open={open !== null} onClose={() => setOpen(null)} title={message.data?.subject ?? "Email"} wide>
        {message.data ? <iframe title="Email preview" sandbox="" srcDoc={message.data.body_html} className="h-[60vh] w-full rounded-xl bg-[#f4f5f2]" /> : <PageLoader />}
      </Modal>
      <Modal
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        title="Reset the demo?"
        description="This deletes everything, including the audit log, and rebuilds the demo company with fresh history. It takes a couple of minutes. Only possible in demo mode."
        footer={
          <>
            <Button onClick={() => setConfirmReset(false)}>Cancel</Button>
            <Button variant="danger" className="flex-1" loading={busy === "reset"} onClick={reset}>
              Reset everything
            </Button>
          </>
        }
      >
        <span />
      </Modal>
    </div>
  );
}
