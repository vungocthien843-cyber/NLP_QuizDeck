import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookCopy, ListChecks, MoreHorizontal, Plus, RotateCcw, Sparkles, Trash2, Undo2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import { Spinner } from "@/components/ui/spinner";
import { UploadBox } from "@/features/study/UploadBox";
import { useDocuments } from "@/features/study/useDocuments";
import { getJSON, request, sendJSON } from "@/lib/api";
import { docTitle, PROCESSING } from "@/lib/format";
import type { ClassStats, DocumentInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { QuestionBank } from "./QuestionBank";

const STATUS: Record<string, { label: string; cls: string }> = {
  ready: { label: "Sẵn sàng", cls: "bg-emerald-50 text-emerald-700" },
  failed: { label: "Lỗi", cls: "bg-red-50 text-red-700" },
};

function Menu({ items }: { items: { label: string; icon: typeof Plus; onClick: () => void; danger?: boolean; hidden?: boolean }[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((v) => !v)} aria-label="Thao tác" aria-haspopup="menu" aria-expanded={open} className="rounded p-1.5 text-muted hover:bg-brand-50 hover:text-ink cursor-pointer"><MoreHorizontal className="size-4" /></button>
      {open && (
        <div role="menu" className="absolute right-0 z-20 mt-1 w-56 rounded-xl border border-line bg-white p-1 shadow-lg">
          {items.filter((i) => !i.hidden).map((i) => (
            <button key={i.label} role="menuitem" onClick={() => { setOpen(false); i.onClick(); }} className={cn("flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm cursor-pointer", i.danger ? "text-red-700 hover:bg-red-50" : "hover:bg-brand-50")}>
              <i.icon className="size-4" /> {i.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function SessionInput({ d }: { d: DocumentInfo }) {
  const qc = useQueryClient();
  const [v, setV] = useState(d.session_no?.toString() ?? "");
  useEffect(() => setV(d.session_no?.toString() ?? ""), [d.session_no]);
  const save = useMutation({
    mutationFn: () => sendJSON(`/documents/${d.id}`, { session_no: v ? Number(v) : null }, "PATCH"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });
  return (
    <input aria-label={`Buổi của ${docTitle(d)}`} type="number" min={1} max={99} value={v} onChange={(e) => setV(e.target.value)} onBlur={() => v !== (d.session_no?.toString() ?? "") && save.mutate()} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} className="h-8 w-14 rounded-md border border-line px-2 text-sm tabular-nums outline-none focus:border-brand-500" placeholder="—" />
  );
}

export function DocumentsAdmin() {
  const docs = useDocuments();
  const qc = useQueryClient();
  const names = useQuery({ queryKey: ["admin-stats"], queryFn: () => getJSON<ClassStats>("/admin/stats") }).data?.error_type_names ?? {};
  const [bank, setBank] = useState<DocumentInfo | null>(null);
  const [upload, setUpload] = useState(false);
  const [confirm, setConfirm] = useState<{ kind: "delete" | "generate"; d: DocumentInfo } | null>(null);
  const [n, setN] = useState("10");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["documents"] });
    qc.invalidateQueries({ queryKey: ["admin-stats"] });
  };
  const act = useMutation({
    mutationFn: async ({ kind, d }: { kind: string; d: DocumentInfo }) => {
      if (kind === "delete") return request(`/documents/${d.id}`, { method: "DELETE" });
      if (kind === "share") return sendJSON(`/documents/${d.id}`, { is_shared: true }, "PATCH");
      if (kind === "unshare") return sendJSON(`/documents/${d.id}`, { is_shared: false }, "PATCH");
      if (kind === "reprocess") return sendJSON(`/admin/documents/${d.id}/reprocess`, {});
      if (kind === "generate") return sendJSON(`/documents/${d.id}/questions/generate`, { n: Number(n) || 10 });
    },
    onSuccess: (_r, { kind, d }) => {
      const t: Record<string, string> = { delete: "Đã xóa", share: "Đã đưa vào thư viện môn học", unshare: "Đã trả về slide riêng của người tải", reprocess: "Đang xử lý lại", generate: "Đang sinh thêm câu hỏi cho" };
      setMsg({ ok: true, text: `${t[kind]} “${docTitle(d)}”.` });
      setConfirm(null);
      refresh();
    },
    onError: (e: Error) => {
      setConfirm(null);
      setMsg({ ok: false, text: e.message });
    },
  });

  if (bank) return <QuestionBank doc={bank} names={names} onBack={() => setBank(null)} />;
  const list = [...(docs.data ?? [])].sort((a, b) => Number(b.is_shared) - Number(a.is_shared) || (a.session_no ?? 999) - (b.session_no ?? 999) || a.id - b.id);

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">{list.filter((d) => d.is_shared).length} bài trong thư viện · {list.filter((d) => !d.is_shared).length} slide riêng của sinh viên</p>
        <Button onClick={() => setUpload((v) => !v)}><Plus className="size-4" /> Tải bài vào thư viện</Button>
      </div>
      {upload && <div className="mt-3 max-w-md"><UploadBox onClose={() => setUpload(false)} onDone={() => { setUpload(false); refresh(); }} /></div>}
      {msg && <p role="status" className={cn("mt-3 rounded-lg px-3 py-2 text-sm", msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800")}>{msg.text}</p>}
      {docs.isPending && <Spinner className="m-6" />}
      <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-white">
        <table className="w-full text-sm">
          <thead className="border-b border-line bg-canvas text-left text-xs text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Buổi</th>
              <th className="px-3 py-2 font-medium">Bài giảng</th>
              <th className="px-3 py-2 font-medium">Thuộc</th>
              <th className="px-3 py-2 font-medium">Trạng thái</th>
              <th className="px-3 py-2 text-right font-medium">Slide</th>
              <th className="px-3 py-2 text-right font-medium">Câu đạt / loại</th>
              <th className="px-3 py-2"><span className="sr-only">Thao tác</span></th>
            </tr>
          </thead>
          <tbody>
            {list.map((d) => {
              const busy = PROCESSING.has(d.status);
              const st = STATUS[d.status] ?? { label: "Đang xử lý", cls: "bg-amber-50 text-amber-700" };
              return (
                <tr key={d.id} className="border-b border-line last:border-0 hover:bg-brand-50/30">
                  <td className="px-3 py-2"><SessionInput d={d} /></td>
                  <td className="px-3 py-2">
                    <button onClick={() => setBank(d)} className="text-left font-medium hover:text-brand-700 hover:underline cursor-pointer">{docTitle(d)}</button>
                    {d.error && <p className="mt-0.5 line-clamp-1 text-xs text-red-700" title={d.error}>{d.error}</p>}
                  </td>
                  <td className="px-3 py-2 text-xs">{d.is_shared ? <span className="inline-flex items-center gap-1 rounded bg-brand-50 px-1.5 py-0.5 text-brand-700"><BookCopy className="size-3" /> Thư viện</span> : <span className="text-muted" title={d.owner_email ?? ""}>Riêng · {d.owner_email?.split("@")[0] ?? "?"}</span>}</td>
                  <td className="px-3 py-2"><span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium", st.cls)}>{busy && <Spinner className="size-3" />}{st.label}</span></td>
                  <td className="px-3 py-2 text-right tabular-nums">{d.num_slides}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{d.num_accepted} <span className="text-muted">/ {d.num_rejected}</span></td>
                  <td className="px-3 py-2 text-right">
                    <Menu items={[
                      { label: "Ngân hàng câu hỏi", icon: ListChecks, onClick: () => setBank(d) },
                      { label: "Sinh thêm câu hỏi", icon: Sparkles, onClick: () => setConfirm({ kind: "generate", d }), hidden: d.status !== "ready" },
                      { label: "Đưa vào thư viện môn học", icon: BookCopy, onClick: () => act.mutate({ kind: "share", d }), hidden: d.is_shared },
                      { label: "Trả về slide riêng", icon: Undo2, onClick: () => act.mutate({ kind: "unshare", d }), hidden: !d.is_shared || !d.owner_email },
                      { label: "Xử lý lại", icon: RotateCcw, onClick: () => act.mutate({ kind: "reprocess", d }), hidden: d.status !== "failed" },
                      { label: "Xóa bài", icon: Trash2, onClick: () => setConfirm({ kind: "delete", d }), danger: true, hidden: busy },
                    ]} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ConfirmDialog open={confirm?.kind === "delete"} title={`Xóa “${confirm ? docTitle(confirm.d) : ""}”?`} confirmLabel="Xóa bài" danger busy={act.isPending} onCancel={() => setConfirm(null)} onConfirm={() => confirm && act.mutate(confirm)}>
        Bài sẽ không còn dùng để học và tạo đề. Điểm các lần làm bài trước vẫn được giữ.
      </ConfirmDialog>
      <ConfirmDialog open={confirm?.kind === "generate"} title={`Sinh thêm câu hỏi cho “${confirm ? docTitle(confirm.d) : ""}”`} confirmLabel="Sinh câu hỏi" busy={act.isPending} onCancel={() => setConfirm(null)} onConfirm={() => confirm && act.mutate(confirm)}>
        <label className="mt-1 block text-sm text-ink">Số câu cần thêm
          <input type="number" min={1} max={100} value={n} onChange={(e) => setN(e.target.value)} className="mt-1 block h-9 w-28 rounded-lg border border-line px-2 outline-none focus:border-brand-500" />
        </label>
        <span className="mt-2 block">Việc sinh câu hỏi gọi LLM (tốn phí) và chạy nền vài phút.</span>
      </ConfirmDialog>
    </div>
  );
}
