import { CheckCircle2, MessagesSquare, Presentation, Search, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { BLOOM_VI, docTitle } from "@/lib/format";
import type { Letter, ReviewItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type QuizPhase, useStudy } from "../study/StudyContext";
import { useDocuments } from "../study/useDocuments";
import { ItemFeedback, ReviewSurvey } from "./Experiment";
import type { ExpStep } from "../study/StudyContext";

type Review = Extract<QuizPhase, { phase: "review" }>;
const LETTERS: Letter[] = ["A", "B", "C", "D"];

function ScoreRing({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score * 10));
  return (
    <div className="relative grid size-20 shrink-0 place-items-center rounded-full" style={{ background: `conic-gradient(var(--color-brand-600) ${pct}%, var(--color-brand-100) 0)` }}>
      <div className="grid size-16 place-items-center rounded-full bg-white text-center leading-none">
        <span>
          <span className="text-xl font-semibold tabular-nums">{score.toFixed(1)}</span>
          <span className="block text-[10px] text-muted">/ 10</span>
        </span>
      </div>
    </div>
  );
}

function Item({ it, n, attemptId, exp }: { it: ReviewItem; n: number; attemptId: number; exp?: ExpStep }) {
  const { openSlide, viewingQuestion, askAbout } = useStudy();
  const docs = useDocuments();
  const src = it.sources[0];
  const docId = it.evidence_document_id ?? src?.document_id ?? null;
  const slide = it.evidence_slide_no ?? src?.slide_no ?? null;
  const doc = docs.data?.find((d) => d.id === docId);
  const viewing = viewingQuestion === it.question_id;

  return (
    <article className={cn("rounded-xl border bg-white p-4", viewing ? "border-brand-500 ring-2 ring-brand-100" : "border-line")}>
      <header className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
        Câu {n}
        {it.bloom_level && <span className="rounded bg-brand-50 px-1.5 py-0.5 normal-case tracking-normal text-brand-700">{BLOOM_VI[it.bloom_level] ?? it.bloom_level}</span>}
        <span className={cn("ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 normal-case tracking-normal", it.is_correct ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700")}>
          {it.is_correct ? <CheckCircle2 className="size-3" /> : <XCircle className="size-3" />}
          {it.is_correct ? "Đúng" : it.chosen ? "Sai" : "Chưa làm"}
        </span>
      </header>
      <p className="mt-2 text-sm font-medium leading-relaxed">{it.stem}</p>

      <ul className="mt-3 space-y-1.5">
        {LETTERS.filter((l) => it.options[l] != null).map((l) => {
          const right = l === it.answer;
          const mine = l === it.chosen;
          return (
            <li key={l} className={cn("rounded-lg border px-3 py-2 text-sm", right ? "border-emerald-200 bg-emerald-50/60" : mine ? "border-red-200 bg-red-50/60" : "border-transparent")}>
              <div className="flex items-start gap-2.5">
                <span className={cn("grid size-5 shrink-0 place-items-center rounded text-[11px] font-semibold", right ? "bg-emerald-600 text-white" : mine ? "bg-red-600 text-white" : "bg-canvas text-muted ring-1 ring-line")}>{l}</span>
                <span className="flex-1">{it.options[l]}</span>
                {(right || mine) && (
                  <span className={cn("shrink-0 text-xs", right ? "text-emerald-700" : "text-red-700")}>
                    {right ? (mine ? "Đáp án đúng · bạn chọn" : "Đáp án đúng") : "Bạn chọn"}
                  </span>
                )}
              </div>
              {(right || mine) && it.rationales[l] && <p className="mt-1.5 pl-7.5 text-xs leading-relaxed text-muted">{it.rationales[l]}</p>}
            </li>
          );
        })}
      </ul>

      {!it.is_correct && it.misconception && (
        <div className="mt-3 rounded-lg border-l-4 border-amber-500 bg-amber-50 p-3 text-sm">
          <p className="flex items-center gap-1.5 font-semibold text-amber-900">
            <Search className="size-3.5" /> Có thể bạn đang nhầm: {it.misconception.ten}
          </p>
          <p className="mt-1 text-amber-900/80">{it.misconception.chan_doan}</p>
          {exp === "1" && <ItemFeedback attemptId={attemptId} questionId={it.question_id} />}
        </div>
      )}

      {it.explanation && (
        <p className="mt-3 text-sm leading-relaxed">
          <span className="font-semibold">Giải thích: </span>
          {it.explanation}
        </p>
      )}

      {(it.evidence || src) && (
        <div className="mt-3 rounded-lg bg-canvas p-3 ring-1 ring-line">
          <p className="text-xs font-semibold text-muted">{it.evidence ? "Trích dẫn từ slide" : "Slide nguồn"}</p>
          <blockquote className="mt-1 text-sm leading-relaxed">
            {it.evidence ? <mark className="rounded bg-amber-100 px-0.5">“{it.evidence}”</mark> : <span className="text-muted">{src!.raw_text.slice(0, 260)}…</span>}
          </blockquote>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-muted">
              {doc ? docTitle(doc) : "Bài đã bị xóa"}
              {slide ? ` · Slide ${slide}` : ""}
              {src?.title ? ` · ${src.title}` : ""}
            </span>
            {doc && slide && (
              <Button size="sm" variant={viewing ? "primary" : "secondary"} onClick={() => openSlide(doc.id, slide, it.evidence, it.question_id)}>
                <Presentation className="size-3.5" /> {viewing ? "Đang xem trên slide" : "Xem trên slide"}
              </Button>
            )}
          </div>
        </div>
      )}
      <div className="mt-3 flex justify-end">
        <Button size="sm" variant="ghost" onClick={() => askAbout(it, n - 1, attemptId)}>
          <MessagesSquare className="size-3.5" /> Hỏi trợ lý về câu này
        </Button>
      </div>
    </article>
  );
}

export function QuizReview({ s }: { s: Review }) {
  const { setQuiz } = useStudy();
  const items = s.review.items;
  const right = items.filter((i) => i.is_correct).length;
  const wrong = items.length - right;
  const [filter, setFilter] = useState<"wrong" | "all">(wrong ? "wrong" : "all");
  const shown = useMemo(() => items.map((it, i) => ({ it, n: i + 1 })).filter(({ it }) => filter === "all" || !it.is_correct), [items, filter]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line p-4">
        <div className="flex items-center gap-4">
          <ScoreRing score={s.attempt.score_10} />
          <div className="min-w-0">
            <p className="font-semibold">Đã chấm xong</p>
            <p className="truncate text-sm text-muted" title={s.label}>{s.label} · {items.length} câu</p>
            <p className="mt-1.5 flex gap-2 text-sm">
              <span className="rounded bg-emerald-50 px-2 py-0.5 text-emerald-700"><b>{right}</b> đúng</span>
              <span className="rounded bg-red-50 px-2 py-0.5 text-red-700"><b>{wrong}</b> sai</span>
            </p>
          </div>
        </div>
        <div className="mt-4 flex gap-2">
          <Button className="flex-1" onClick={() => setQuiz({ phase: "setup" })}>Làm đề mới</Button>
        </div>
        <Segmented
          className="mt-3"
          label="Lọc câu"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "wrong", label: `Câu sai (${wrong})` },
            { value: "all", label: `Tất cả (${items.length})` },
          ]}
        />
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-canvas p-3">
        {s.exp && <ReviewSurvey exp={s.exp} attemptId={s.attempt.attempt_id} />}
        {shown.length === 0 ? (
          <p className="p-4 text-center text-sm text-muted">Bạn không sai câu nào. Chọn “Tất cả” để xem lại toàn bộ đề.</p>
        ) : (
          shown.map(({ it, n }) => <Item key={it.question_id} it={it} n={n} attemptId={s.attempt.attempt_id} exp={s.exp} />)
        )}
      </div>
    </div>
  );
}
