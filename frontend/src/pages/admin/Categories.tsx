import { useQuery } from "@tanstack/react-query";
import { Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { useAction, useMe } from "../../api/hooks";
import type { Group } from "../../api/types";
import { Badge, Button, Card, ErrorNote, Field, Input, Modal, PageHeader, PageLoader, Select, Toggle } from "../../components/ui";
import { GROUP } from "../../lib/format";

interface Cat {
  id: number;
  name: string;
  group: Group;
  description: string | null;
  gl_code: string | null;
  quote_required: boolean;
  confidential_default: boolean;
  is_active: boolean;
  sort_order: number;
  usage: number;
}

const BLANK: Omit<Cat, "id" | "usage"> = { name: "", group: "general", description: "", gl_code: "", quote_required: true, confidential_default: false, is_active: true, sort_order: 100 };

export default function Categories() {
  const { data: me } = useMe();
  const { data, isLoading, error } = useQuery({ queryKey: ["categories-admin"], queryFn: () => api.get<Cat[]>("/api/admin/categories") });
  const [editing, setEditing] = useState<Cat | "new" | null>(null);
  const canEdit = !!me?.capabilities.can_manage_policy;
  if (isLoading) return <PageLoader />;
  if (error || !data) return <ErrorNote error={error} />;
  return (
    <div>
      <PageHeader
        title="Categories"
        subtitle="Placeholder list until Tom's final categories arrive. The type decides which approval rules apply: IT always goes to the COO, and travel has its own limit."
        actions={canEdit ? <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setEditing("new")}>Add category</Button> : undefined}
      />
      <Card padded={false}>
        <ul className="divide-y divide-zinc-100">
          {data.map((c) => (
            <li key={c.id} className="flex items-center gap-3 px-4 py-3 sm:px-5">
              <span className={`size-2.5 shrink-0 rounded-full ${GROUP[c.group].dot}`} />
              <div className="min-w-0 flex-1">
                <p className="text-[14px] font-medium">
                  {c.name} {!c.is_active && <Badge tone="zinc">Retired</Badge>}
                </p>
                <p className="truncate text-[12.5px] text-zinc-500">
                  {GROUP[c.group].label}
                  {c.gl_code && ` · GL ${c.gl_code}`} · {c.quote_required ? "Quote required" : "No quote needed"}
                  {c.confidential_default && " · Confidential by default"} · used {c.usage} times
                </p>
              </div>
              {canEdit && (
                <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(c)}>
                  Edit
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Card>
      {editing && <CategoryModal cat={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function CategoryModal({ cat, onClose }: { cat: Cat | null; onClose: () => void }) {
  const [f, setF] = useState(cat ? { ...cat } : { ...BLANK });
  const save = useAction(
    () => {
      const body = { name: f.name, group: f.group, description: f.description || null, gl_code: f.gl_code || null, quote_required: f.quote_required, confidential_default: f.confidential_default, is_active: f.is_active, sort_order: f.sort_order };
      return cat ? api.patch(`/api/admin/categories/${cat.id}`, body) : api.post("/api/admin/categories", body);
    },
    { success: "Saved", invalidate: [["categories-admin"], ["lookups"]], onSuccess: onClose },
  );
  return (
    <Modal open onClose={onClose} title={cat ? `Edit ${cat.name}` : "New category"} description={cat?.usage ? "This category is in use. Changes apply to new requests. Existing ones keep their history." : undefined} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" className="flex-1" loading={save.isPending} disabled={f.name.trim().length < 2} onClick={() => save.mutate(undefined)}>Save</Button></>}>
      <div className="space-y-3">
        <Field label="Name">
          <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type" hint="Decides which rules apply">
            <Select value={f.group} onChange={(e) => setF({ ...f, group: e.target.value as Group })}>
              <option value="it">IT</option>
              <option value="travel">Travel</option>
              <option value="general">General</option>
            </Select>
          </Field>
          <Field label="GL code" optional>
            <Input value={f.gl_code ?? ""} onChange={(e) => setF({ ...f, gl_code: e.target.value })} />
          </Field>
        </div>
        <Field label="Description" optional>
          <Input value={f.description ?? ""} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
        <Toggle checked={f.quote_required} onChange={(v) => setF({ ...f, quote_required: v })} label="Quote required" description="People can still say why there isn't one." />
        <Toggle checked={f.confidential_default} onChange={(v) => setF({ ...f, confidential_default: v })} label="Confidential by default" description="For legal, HR and other sensitive spend." />
        <Toggle checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} label="Available for new requests" />
      </div>
    </Modal>
  );
}
