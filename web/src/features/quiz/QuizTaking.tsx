import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Flag, Timer } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import { getJSON, sendJSON } from "@/lib/api";
import { BLOOM_VI, fmtClock } from "@/lib/format";
import type { AttemptOut, Letter, ReviewOut } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type QuizPhase, useStudy } from "../study/StudyContext";

type Taking = Extract<QuizPhase, { phase: "taking" }>;
const LETTERS: Letter[] = ["A", "B", "C", "D"];

function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

export function QuizTaking({ s }: { s: Taking }) {
  const { setQuiz } = useStudy();
  const qc = useQueryClient();
  const qs = s.quiz.questions;
  const total = qs.length;
  const q = qs[s.index];
  const done = qs.filter((x) => s.answers[x.question_id]).length;
  const missing = qs.map((x, i) => (s.answers[x.question_id] ? -1 : i)).filter((i) => i >= 0);
  const left = Math.round((s.deadline - useNow()) / 1000);
  const [confirm, setConfirm] = useState<"missing" | "quit" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const update = useCallback((patch: Partial<Taking>) => setQuiz({ ...s, ...patch }), [s, setQuiz]);
  const go = useCallback((i: number) => update({ index: Math.max(0, Math.min(total - 1, i)) }), [update, total]);
  const choose = useCallback(
    (l: Letter) => update({ answers: { ...s.answers, [q.question_id]: l }, index: Math.min(total - 1, s.index + 1) }),
    [update, s.answers, s.index, q.question_id, total],
  );
  const toggleFlag = useCallback(
    () => update({ flagged: s.flagged.includes(q.question_id) ? s.flagged.filter((x) => x !== q.question_id) : [...s.flagged, q.question_id] }),
    [update, s.flagged, q.question_id],
  );

  const submit = useMutation({
    mutationFn: async (allowUnanswered: boolean) => {
      const attempt = await sendJSON<AttemptOut>("/attempts", { quiz_id: s.quiz.quiz_id, answers: s.answers, allow_unanswered: allowUnanswered });
      const review = await getJSON<ReviewOut>(`/attempts/${attempt.attempt_id}/review`);
      return { attempt, review };
    },
    onSuccess: ({ attempt, review }) => {
      qc.invalidateQueries({ queryKey: ["profile"] });
      qc.invalidateQueries({ queryKey: ["my-attempts"] });
      qc.invalidateQueries({ queryKey: ["experiment"] });
      setQuiz({ phase: "review", quiz: s.quiz, label: s.label, attempt, review, exp: s.exp });
    },
    onError: (e: Error) => {
      setConfirm(null);
      setErr(e.message);
    },
  });

  // Phím tắt: A–D hoặc 1–4 chọn đáp án, ←/→ chuyển câu, F đánh dấu
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (confirm || e.ctrlKey || e.metaKey || e.altKey || t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;
      const k = e.key.toUpperCase();
      const idx = LETTERS.indexOf(k as Letter) >= 0 ? LETTERS.indexOf(k as Letter) : ["1", "2", "3", "4"].indexOf(k);
      if (idx >= 0 && q.options[LETTERS[idx]]) choose(LETTERS[idx]);
      else if (e.key === "ArrowRight") go(s.index + 1);
      else if (e.key === "ArrowLeft") go(s.index - 1);
      else if (k === "F") toggleFlag();
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirm, q, choose, go, toggleFlag, s.index]);

  const trySubmit = () => {
    setErr(null);
    if (missing.length && left > 0) setConfirm("missing");
    else submit.mutate(missing.length > 0);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <p className="min-w-0 truncate text-sm font-semibold" title={s.label}>{s.label}</p>
          <span className={cn("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-sm font-medium tabular-nums", left <= 60 ? "bg-red-50 text-red-700" : "bg-brand-50 text-brand-700")} role="timer" aria-label="Thời gian còn lại">
            <Timer className="size-3.5" />
            {left > 0 ? fmtClock(left) : "Hết giờ"}
          </span>
        </div>
        <div className="mt-2 flex items-center gap-2 text-xs text-muted">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-brand-100">
            <div className="h-full bg-brand-600 transition-[width]" style={{ width: `${(done / total) * 100}%` }} />
          </div>
          {done}/{total}
        </div>
        {s.quiz.notice && <p className="mt-2 rounded-md bg-amber-50 p-2 text-xs text-amber-900">{s.quiz.notice}</p>}
        <nav aria-label="Danh sách câu" className="mt-3 grid grid-cols-10 gap-1">
          {qs.map((x, i) => {
            const answered = !!s.answers[x.question_id];
            const flagged = s.flagged.includes(x.question_id);
            return (
              <button
                key={x.question_id}
                onClick={() => go(i)}
                aria-label={`Câu ${i + 1}${answered ? ", đã làm" : ""}${flagged ? ", đã đánh dấu" : ""}`}
                aria-current={i === s.index ? "step" : undefined}
                className={cn(
                  "relative h-7 rounded text-xs font-medium tabular-nums cursor-pointer",
                  answered ? "bg-brand-600 text-white" : "bg-canvas text-muted ring-1 ring-line hover:ring-brand-200",
                  i === s.index && "outline-2 outline-offset-1 outline-brand-800",
                )}
              >
                {i + 1}
                {flagged && <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full bg-amber-500 ring-1 ring-white" />}
              </button>
            );
          })}
        </nav>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
          Câu {s.index + 1}/{total}
          {q.bloom_level && <span className="rounded bg-brand-50 px-1.5 py-0.5 normal-case tracking-normal text-brand-700">{BLOOM_VI[q.bloom_level] ?? q.bloom_level}</span>}
          <button onClick={toggleFlag} aria-pressed={s.flagged.includes(q.question_id)} className={cn("ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 normal-case tracking-normal cursor-pointer", s.flagged.includes(q.question_id) ? "bg-amber-50 text-amber-800" : "hover:bg-brand-50")}>
            <Flag className="size-3" /> {s.flagged.includes(q.question_id) ? "Đã đánh dấu" : "Đánh dấu"}
          </button>
        </div>
        <p className="mt-2 font-medium leading-relaxed">{q.stem}</p>
        <div role="radiogroup" aria-label={`Đáp án câu ${s.index + 1}`} className="mt-4 space-y-2">
          {LETTERS.filter((l) => q.options[l] != null).map((l) => {
            const on = s.answers[q.question_id] === l;
            return (
              <button
                key={l}
                role="radio"
                aria-checked={on}
                onClick={() => choose(l)}
                className={cn("flex w-full items-start gap-3 rounded-lg border p-3 text-left text-sm transition-colors cursor-pointer", on ? "border-brand-600 bg-brand-50" : "border-line bg-white hover:border-brand-200")}
              >
                <span className={cn("grid size-6 shrink-0 place-items-center rounded-md text-xs font-semibold", on ? "bg-brand-600 text-white" : "bg-canvas text-muted ring-1 ring-line")}>{l}</span>
                <span className="pt-0.5">{q.options[l]}</span>
              </button>
            );
          })}
        </div>
        <p className="mt-4 text-xs text-muted">Phím tắt: A–D chọn đáp án · ← → chuyển câu · F đánh dấu</p>
        {err && <p role="alert" className="mt-3 text-sm text-red-700">{err}</p>}
      </div>

      <div className="flex items-center gap-2 border-t border-line px-4 py-3">
        <Button variant="secondary" size="sm" disabled={s.index === 0} onClick={() => go(s.index - 1)} aria-label="Câu trước">
          <ChevronLeft className="size-4" />
        </Button>
        <Button variant="secondary" size="sm" disabled={s.index >= total - 1} onClick={() => go(s.index + 1)} aria-label="Câu sau">
          <ChevronRight className="size-4" />
        </Button>
        <button onClick={() => setConfirm("quit")} className="ml-1 text-xs text-muted hover:text-ink hover:underline cursor-pointer">
          Bỏ bài
        </button>
        <Button className="ml-auto" onClick={trySubmit} disabled={submit.isPending}>
          {submit.isPending ? "Đang chấm…" : "Nộp bài"}
        </Button>
      </div>

      <ConfirmDialog
        open={confirm === "missing"}
        title={`Còn ${missing.length} câu chưa làm`}
        confirmLabel="Làm tiếp"
        onConfirm={() => {
          setConfirm(null);
          go(missing[0]);
        }}
        onCancel={() => setConfirm(null)}
      >
        Câu {missing.map((i) => i + 1).join(", ")} chưa có đáp án. Hãy làm hết rồi nộp bài.
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === "quit"}
        title="Bỏ bài đang làm?"
        confirmLabel="Bỏ bài"
        danger
        onConfirm={() => setQuiz({ phase: "setup" })}
        onCancel={() => setConfirm(null)}
      >
        Các câu đã chọn sẽ không được lưu và không tính điểm.
      </ConfirmDialog>
    </div>
  );
}
