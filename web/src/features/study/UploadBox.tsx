import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileUp, X } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { uploadFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { DocumentInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useQuota } from "./useDocuments";

const ACCEPT = [".pptx", ".pdf"];

export function UploadBox({ onDone, onClose }: { onDone: (d: DocumentInfo) => void; onClose: () => void }) {
  const { me } = useAuth();
  const qc = useQueryClient();
  const quota = useQuota();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [pct, setPct] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const q = quota.data;
  const full = q && !q.unlimited && q.used_docs >= q.max_docs;

  const pick = (f: File | undefined) => {
    setErr(null);
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPT.includes(ext)) return setErr("Chỉ nhận file .pptx hoặc .pdf");
    if (q && f.size > q.max_upload_mb * 1024 * 1024) return setErr(`File vượt quá ${q.max_upload_mb} MB`);
    setFile(f);
  };

  const up = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("file", file!);
      return uploadFile<DocumentInfo>("/documents", form, setPct);
    },
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["quota"] });
      onDone(d);
    },
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <div className="rounded-xl border border-line bg-white p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-semibold">Tải slide lên</p>
        <button onClick={onClose} aria-label="Đóng" className="rounded p-1 text-muted hover:bg-brand-50 cursor-pointer">
          <X className="size-4" />
        </button>
      </div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          pick(e.dataTransfer.files[0]);
        }}
        className={cn(
          "grid cursor-pointer place-items-center rounded-lg border-2 border-dashed px-3 py-5 text-center text-sm transition-colors",
          drag ? "border-brand-500 bg-brand-50" : "border-line hover:border-brand-200 hover:bg-brand-50/50",
        )}
      >
        <FileUp className="mb-1 size-5 text-brand-600" />
        {file ? <span className="font-medium break-all">{file.name}</span> : <span>Kéo thả hoặc bấm để chọn file</span>}
        <span className="mt-0.5 text-xs text-muted">PPTX hoặc PDF · tối đa {q?.max_upload_mb ?? 50} MB</span>
      </div>
      <input ref={input} type="file" accept={ACCEPT.join(",")} hidden onChange={(e) => pick(e.target.files?.[0])} />

      {q && !q.unlimited && (
        <p className="mt-2 text-xs text-muted">
          Bạn đã tải {q.used_docs}/{q.max_docs} bài. Slide bạn tải lên chỉ mình bạn thấy.
        </p>
      )}
      {me?.is_admin && <p className="mt-2 text-xs text-muted">Bài quản trị viên tải lên sẽ vào thư viện môn học.</p>}
      {full && <p className="mt-2 text-xs text-red-700">Bạn đã dùng hết hạn mức. Xóa bớt bài cũ để tải bài mới.</p>}
      {err && <p role="alert" className="mt-2 text-xs text-red-700">{err}</p>}
      {up.isPending && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-brand-100" aria-label={`Đang tải ${pct}%`}>
          <div className="h-full bg-brand-600 transition-[width]" style={{ width: `${pct}%` }} />
        </div>
      )}
      <Button className="mt-3 w-full" disabled={!file || up.isPending || !!full} onClick={() => up.mutate()}>
        {up.isPending ? `Đang tải lên ${pct}%` : "Tải lên và tạo câu hỏi"}
      </Button>
    </div>
  );
}
