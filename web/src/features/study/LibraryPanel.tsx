import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, FileText, Lock, PanelLeftClose, Plus, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { ConfirmDialog } from "@/components/ui/confirm";
import { Spinner } from "@/components/ui/spinner";
import { request } from "@/lib/api";
import { docTitle, PROCESSING, STEPS } from "@/lib/format";
import type { DocumentInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useStudy } from "./StudyContext";
import { UploadBox } from "./UploadBox";
import { useDocuments } from "./useDocuments";

function Progress({ d }: { d: DocumentInfo }) {
  const cur = Math.max(0, STEPS.findIndex((s) => s.key === d.status));
  const step = STEPS[cur];
  return (
    <div className="mt-2">
      <div className="flex gap-1" aria-hidden>
        {STEPS.map((s, i) => (
          <span key={s.key} className={cn("h-1 flex-1 rounded-full", i < cur ? "bg-brand-600" : i === cur ? "animate-pulse bg-brand-500" : "bg-brand-100")} />
        ))}
      </div>
      <p className="mt-1 text-xs text-muted">
        Bước {cur + 1}/3: {step.label}
        {d.status === "generating" && d.num_accepted > 0 ? ` (${d.num_accepted} câu)` : ""}…
      </p>
    </div>
  );
}

function DocItem({ d, active, onSelect, onDelete }: { d: DocumentInfo; active: boolean; onSelect: () => void; onDelete: () => void }) {
  const busy = PROCESSING.has(d.status);
  return (
    <li className="group relative">
      <button
        onClick={onSelect}
        aria-current={active ? "true" : undefined}
        className={cn(
          "w-full rounded-lg border px-3 py-2.5 text-left transition-colors cursor-pointer",
          active ? "border-brand-200 bg-brand-50" : "border-transparent hover:bg-brand-50/60",
        )}
      >
        <div className="flex items-start gap-2.5 pr-6">
          <FileText className={cn("mt-0.5 size-4 shrink-0", active ? "text-brand-700" : "text-muted")} />
          <div className="min-w-0">
            <p className={cn("text-sm leading-snug", active && "font-medium text-brand-800")}>{docTitle(d)}</p>
            <p className="mt-0.5 text-xs text-muted">
              {d.session_no ? `Buổi ${d.session_no} · ` : ""}
              {d.num_slides} slide · {d.num_accepted} câu hỏi
            </p>
          </div>
        </div>
        {busy && <Progress d={d} />}
        {d.status === "failed" && (
          <p className="mt-1.5 flex items-start gap-1 text-xs text-red-700">
            <AlertCircle className="mt-0.5 size-3 shrink-0" /> {d.error || "Xử lý lỗi"}
          </p>
        )}
      </button>
      {d.can_edit && !busy && (
        <button
          onClick={onDelete}
          aria-label={`Xóa ${docTitle(d)}`}
          className="absolute right-2 top-2.5 rounded p-1 text-muted opacity-0 transition-opacity hover:bg-red-50 hover:text-red-700 focus:opacity-100 group-hover:opacity-100 cursor-pointer"
        >
          <Trash2 className="size-3.5" />
        </button>
      )}
    </li>
  );
}

export function LibraryPanel({ onCollapse }: { onCollapse?: () => void }) {
  const docs = useDocuments();
  const qc = useQueryClient();
  const { docId, selectDoc } = useStudy();
  const [q, setQ] = useState("");
  const [upload, setUpload] = useState(false);
  const [toDelete, setToDelete] = useState<DocumentInfo | null>(null);

  const del = useMutation({
    mutationFn: (id: number) => request(`/documents/${id}`, { method: "DELETE" }),
    onSuccess: (_r, id) => {
      if (id === docId) selectDoc(null);
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["quota"] });
      setToDelete(null);
    },
  });

  const { shared, mine } = useMemo(() => {
    const k = q.trim().toLowerCase();
    const list = (docs.data ?? [])
      .filter((d) => !k || docTitle(d).toLowerCase().includes(k))
      .sort((a, b) => (a.session_no ?? 999) - (b.session_no ?? 999) || docTitle(a).localeCompare(docTitle(b), "vi"));
    return { shared: list.filter((d) => d.is_shared), mine: list.filter((d) => !d.is_shared) };
  }, [docs.data, q]);

  const section = (title: string, list: DocumentInfo[], empty: string, icon?: React.ReactNode) => (
    <section className="mt-4">
      <h3 className="flex items-center gap-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-muted">
        {icon}
        {title}
        <span className="font-normal">({list.length})</span>
      </h3>
      {list.length === 0 ? (
        <p className="px-1 py-2 text-xs text-muted">{empty}</p>
      ) : (
        <ul className="mt-1 space-y-0.5">
          {list.map((d) => (
            <DocItem key={d.id} d={d} active={d.id === docId} onSelect={() => selectDoc(d.id)} onDelete={() => setToDelete(d)} />
          ))}
        </ul>
      )}
    </section>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 px-3 pt-3">
        <h2 className="mr-auto font-semibold">Bài giảng</h2>
        <button
          onClick={() => setUpload((v) => !v)}
          aria-expanded={upload}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-sm font-medium text-brand-700 hover:bg-brand-50 cursor-pointer"
        >
          <Plus className="size-4" /> Tải slide
        </button>
        {onCollapse && (
          <button onClick={onCollapse} aria-label="Thu gọn danh sách bài" className="hidden rounded p-1.5 text-muted hover:bg-brand-50 lg:block cursor-pointer">
            <PanelLeftClose className="size-4" />
          </button>
        )}
      </div>
      <div className="px-3 pt-2">
        {upload && (
          <div className="mb-3">
            <UploadBox
              onClose={() => setUpload(false)}
              onDone={(d) => {
                setUpload(false);
                selectDoc(d.id);
              }}
            />
          </div>
        )}
        <label className="relative block">
          <span className="sr-only">Tìm bài giảng</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Tìm bài giảng…"
            className="h-9 w-full rounded-lg border border-line bg-white pl-8 pr-3 text-sm outline-none focus:border-brand-500"
          />
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {docs.isPending && <Spinner className="m-4" />}
        {docs.isError && <p className="m-3 text-sm text-red-700">{docs.error.message}</p>}
        {docs.data && (
          <>
            {section("Thư viện môn học", shared, "Chưa có bài nào.")}
            {section("Slide của tôi", mine, "Bạn chưa tải slide riêng nào.", <Lock className="size-3" />)}
          </>
        )}
      </div>
      <ConfirmDialog
        open={!!toDelete}
        title={`Xóa “${toDelete ? docTitle(toDelete) : ""}”?`}
        confirmLabel="Xóa bài"
        danger
        busy={del.isPending}
        onCancel={() => setToDelete(null)}
        onConfirm={() => toDelete && del.mutate(toDelete.id)}
      >
        Slide và câu hỏi của bài này sẽ không còn dùng để học và tạo đề. Điểm các lần làm bài trước vẫn được giữ.
        {del.isError && <span className="mt-2 block text-red-700">{del.error.message}</span>}
      </ConfirmDialog>
    </div>
  );
}
