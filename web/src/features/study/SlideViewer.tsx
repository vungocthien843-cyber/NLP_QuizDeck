import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Highlighter, Lock, Presentation, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Spinner } from "@/components/ui/spinner";
import { getJSON } from "@/lib/api";
import { docTitle, PROCESSING, slideImageUrl } from "@/lib/format";
import type { SlidesOut } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useStudy } from "./StudyContext";
import { useDocuments } from "./useDocuments";

function isTyping(el: EventTarget | null) {
  const t = el as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}

export function SlideViewer() {
  const { docId, slideNo, highlight, goToSlide, openSlide, quiz } = useStudy();
  const docs = useDocuments();
  const doc = docs.data?.find((d) => d.id === docId);
  const locked = quiz.phase === "taking";
  const ready = doc && !PROCESSING.has(doc.status);
  const slides = useQuery({
    queryKey: ["slides", docId, doc?.status],
    queryFn: () => getJSON<SlidesOut>(`/documents/${docId}/slides`),
    enabled: !!docId && !!ready,
  });
  const n = slides.data?.num_slides ?? 0;
  const cur = Math.min(slideNo, Math.max(n, 1));
  const info = slides.data?.slides[cur - 1];
  const [notesOpen, setNotesOpen] = useState(false);
  const strip = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (locked || !n) return;
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") cur < n && goToSlide(cur + 1);
      else if (e.key === "ArrowLeft" || e.key === "PageUp") cur > 1 && goToSlide(cur - 1);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [locked, n, cur, goToSlide]);

  useEffect(() => {
    strip.current?.querySelector(`[data-slide="${cur}"]`)?.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
    setNotesOpen(false);
  }, [cur, docId]);

  if (!docId || (docs.data && !doc)) {
    return (
      <div className="grid h-full place-items-center p-8 text-center">
        <div className="max-w-sm">
          <Presentation className="mx-auto size-10 text-brand-200" />
          <h2 className="mt-3 font-semibold">Chọn một bài giảng để bắt đầu</h2>
          <p className="mt-1 text-sm text-muted">
            Xem slide ở đây, làm trắc nghiệm ở cột bên phải. Dùng phím ← → để chuyển slide.
          </p>
        </div>
      </div>
    );
  }
  if (!doc || (ready && slides.isPending)) return <div className="grid h-full place-items-center"><Spinner /></div>;
  if (!ready) {
    return (
      <div className="grid h-full place-items-center p-8 text-center text-sm text-muted">
        <div>
          <Spinner className="mx-auto mb-3" />
          “{docTitle(doc)}” đang được xử lý. Slide sẽ hiện khi xong.
        </div>
      </div>
    );
  }
  if (slides.isError) return <p className="p-6 text-sm text-red-700">{slides.error.message}</p>;
  if (!n) return <p className="p-6 text-sm text-muted">Bài này chưa có ảnh slide.</p>;

  const ratio = info?.width && info?.height ? `${info.width} / ${info.height}` : "16 / 9";

  return (
    <div className="relative flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-line bg-white px-4 py-2">
        <h2 className="min-w-0 flex-1 truncate text-sm font-medium" title={docTitle(doc)}>
          {docTitle(doc)}
          {info?.title && <span className="font-normal text-muted"> · {info.title}</span>}
        </h2>
        <button aria-label="Slide trước" disabled={cur <= 1} onClick={() => goToSlide(cur - 1)} className="rounded-md p-1.5 hover:bg-brand-50 disabled:opacity-30 cursor-pointer">
          <ChevronLeft className="size-4" />
        </button>
        <label className="flex items-center gap-1 text-sm tabular-nums text-muted">
          <span className="sr-only">Đi tới slide</span>
          <select value={cur} onChange={(e) => goToSlide(Number(e.target.value))} className="rounded-md border border-line bg-white px-1.5 py-1 text-ink">
            {Array.from({ length: n }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {i + 1}
              </option>
            ))}
          </select>
          / {n}
        </label>
        <button aria-label="Slide sau" disabled={cur >= n} onClick={() => goToSlide(cur + 1)} className="rounded-md p-1.5 hover:bg-brand-50 disabled:opacity-30 cursor-pointer">
          <ChevronRight className="size-4" />
        </button>
      </div>

      {highlight && (
        <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-xs text-amber-900">
          <Highlighter className="size-3.5" />
          <span className="flex-1">Đang tô vàng câu trích dẫn làm căn cứ cho đáp án.</span>
          <button onClick={() => openSlide(doc.id, cur)} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-amber-100 cursor-pointer">
            <X className="size-3" /> Bỏ tô
          </button>
        </div>
      )}

      <div className={cn("min-h-0 flex-1 overflow-auto p-4 sm:p-6", locked && "pointer-events-none select-none blur-md")} aria-hidden={locked}>
        <figure className="mx-auto max-w-5xl">
          <div className="overflow-hidden rounded-lg border border-line bg-white shadow-sm" style={{ aspectRatio: ratio }}>
            <img
              key={`${doc.id}-${cur}-${highlight ?? ""}`}
              src={slideImageUrl(doc.id, cur, highlight)}
              alt={info?.title ? `Slide ${cur}: ${info.title}` : `Slide ${cur}`}
              className="size-full object-contain"
            />
          </div>
          {info?.notes && (
            <figcaption className="mt-3 rounded-lg bg-white p-3 text-sm text-muted ring-1 ring-line">
              <span className="font-medium text-ink">Ghi chú của giảng viên: </span>
              <span className={cn(!notesOpen && "line-clamp-2")}>{info.notes}</span>
              {info.notes.length > 160 && (
                <button onClick={() => setNotesOpen((v) => !v)} className="ml-1 text-brand-700 hover:underline cursor-pointer">
                  {notesOpen ? "Thu gọn" : "Xem thêm"}
                </button>
              )}
            </figcaption>
          )}
        </figure>
      </div>

      <div ref={strip} className={cn("flex gap-2 overflow-x-auto border-t border-line bg-white px-4 py-2", locked && "invisible")}>
        {Array.from({ length: n }, (_, i) => i + 1).map((s) => (
          <button
            key={s}
            data-slide={s}
            onClick={() => goToSlide(s)}
            aria-label={`Slide ${s}`}
            aria-current={s === cur ? "true" : undefined}
            className={cn("relative h-12 shrink-0 overflow-hidden rounded border-2 bg-canvas cursor-pointer", s === cur ? "border-brand-600" : "border-transparent hover:border-brand-200")}
            style={{ aspectRatio: ratio }}
          >
            <img src={slideImageUrl(doc.id, s)} alt="" loading="lazy" className="size-full object-cover" />
            <span className="absolute bottom-0 right-0 rounded-tl bg-ink/70 px-1 text-[10px] text-white">{s}</span>
          </button>
        ))}
      </div>

      {locked && (
        <div className="absolute inset-0 grid place-items-center p-6">
          <div className="max-w-xs rounded-xl border border-line bg-white p-5 text-center shadow-lg">
            <Lock className="mx-auto size-5 text-brand-600" />
            <p className="mt-2 font-medium">Slide tạm ẩn khi làm bài</p>
            <p className="mt-1 text-sm text-muted">Nộp bài xong, slide sẽ hiện lại kèm trích dẫn cho từng câu.</p>
          </div>
        </div>
      )}
    </div>
  );
}
