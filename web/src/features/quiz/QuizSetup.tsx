import { useMutation } from "@tanstack/react-query";
import { Check, Target } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { sendJSON } from "@/lib/api";
import { docTitle } from "@/lib/format";
import type { Difficulty, Quiz } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useStudy } from "../study/StudyContext";
import { useDocuments } from "../study/useDocuments";
import { ExperimentBox, useExperiment } from "./Experiment";

const MIN_Q = 10;
const COUNTS = ["10", "15", "20", "30"] as const;
const LEVELS: { value: "mix" | Difficulty; label: string }[] = [
  { value: "mix", label: "Trộn" },
  { value: "easy", label: "Dễ" },
  { value: "medium", label: "Vừa" },
  { value: "hard", label: "Khó" },
];
const LEVEL_VI: Record<string, string> = { easy: "Dễ", medium: "Vừa", hard: "Khó" };

export function QuizSetup() {
  const docs = useDocuments();
  const ex = useExperiment();
  const { docId, setQuiz } = useStudy();
  const usable = useMemo(() => (docs.data ?? []).filter((d) => d.status === "ready" && d.num_accepted > 0), [docs.data]);
  const [picked, setPicked] = useState<number[]>([]);
  const [n, setN] = useState("10");
  const [level, setLevel] = useState<"mix" | Difficulty>("mix");
  const [err, setErr] = useState<string | null>(null);

  // Mặc định chọn bài đang xem
  useEffect(() => {
    if (docId && usable.some((d) => d.id === docId)) setPicked((p) => (p.length ? p : [docId]));
  }, [docId, usable]);

  const avail = usable.filter((d) => picked.includes(d.id)).reduce((s, d) => s + d.num_accepted, 0);
  const count = Number(n);

  const create = useMutation({
    mutationFn: (mode: "normal" | "weakness") =>
      sendJSON<Quiz>("/quizzes", {
        scope: { document_ids: picked },
        n: count,
        difficulty: level === "mix" ? null : level,
        mode,
      }),
    onSuccess: (quiz) => {
      const names = usable.filter((d) => picked.includes(d.id)).map(docTitle);
      let label = names.length > 2 ? `${names.length} bài` : names.join(" + ");
      if (quiz.mode === "weakness") label = `Luyện điểm yếu · ${label}`;
      else if (level !== "mix") label += ` · ${LEVEL_VI[level]}`;
      setQuiz({
        phase: "taking",
        quiz,
        label,
        answers: {},
        flagged: [],
        index: 0,
        deadline: Date.now() + quiz.questions.length * 60_000,
      });
    },
    onError: (e: Error) => setErr(e.message),
  });

  const start = (mode: "normal" | "weakness") => {
    setErr(null);
    if (!picked.length) return setErr("Chọn ít nhất một bài đã có câu hỏi.");
    if (avail < MIN_Q) return setErr(`Phạm vi đã chọn mới có ${avail} câu, chưa đủ ${MIN_Q}. Chọn thêm bài.`);
    if (count > avail) return setErr(`Phạm vi đã chọn chỉ có ${avail} câu. Giảm số câu hoặc chọn thêm bài.`);
    create.mutate(mode);
  };

  if (ex && ex.step !== "done")
    return (
      <div className="p-4">
        <ExperimentBox ex={ex} />
      </div>
    );

  return (
    <div className="space-y-5 p-4">
      {ex && <ExperimentBox ex={ex} />}
      <div>
        <h3 className="text-sm font-semibold">Chọn bài để tạo đề</h3>
        {usable.length === 0 ? (
          <p className="mt-2 text-sm text-muted">Chưa có bài nào có câu hỏi.</p>
        ) : (
          <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto pr-1">
            {usable.map((d) => {
              const on = picked.includes(d.id);
              return (
                <li key={d.id}>
                  <label className={cn("flex cursor-pointer items-center gap-2.5 rounded-lg border px-2.5 py-2 text-sm", on ? "border-brand-200 bg-brand-50" : "border-line hover:bg-brand-50/50")}>
                    <input type="checkbox" className="peer sr-only" checked={on} onChange={() => setPicked((p) => (on ? p.filter((x) => x !== d.id) : [...p, d.id]))} />
                    <span className={cn("grid size-4 shrink-0 place-items-center rounded border peer-focus-visible:outline-2 peer-focus-visible:outline-brand-600", on ? "border-brand-600 bg-brand-600 text-white" : "border-muted/50 bg-white")}>
                      {on && <Check className="size-3" strokeWidth={3} />}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{docTitle(d)}</span>
                    <span className="shrink-0 text-xs text-muted">{d.num_accepted} câu</span>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold">Số câu</h3>
        <Segmented label="Số câu" value={n} onChange={setN} options={COUNTS.map((c) => ({ value: c, label: c }))} />
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold">Mức độ khó</h3>
        <Segmented label="Mức độ khó" value={level} onChange={setLevel} options={LEVELS} />
      </div>

      <p className="rounded-lg bg-canvas p-3 text-xs text-muted ring-1 ring-line">
        <span className="font-semibold text-ink">{avail}</span> câu có sẵn trong phạm vi đã chọn · Thời gian 1 phút/câu ·
        Cơ cấu: Nhớ 40%, Hiểu 40%, Vận dụng 20%.
      </p>

      {err && <p role="alert" className="text-sm text-red-700">{err}</p>}

      <div className="space-y-2">
        <Button className="w-full" size="lg" disabled={create.isPending} onClick={() => start("normal")}>
          Bắt đầu làm bài · {count} câu
        </Button>
        <Button variant="secondary" className="w-full" disabled={create.isPending} onClick={() => start("weakness")}>
          <Target className="size-4 text-brand-600" /> Luyện điểm yếu của tôi
        </Button>
        <p className="text-xs text-muted">
          Luyện điểm yếu ưu tiên những ý bạn hay nhầm, với phương án sai đúng kiểu hiểu nhầm đó, để kiểm tra bạn đã sửa được chưa.
        </p>
      </div>
    </div>
  );
}
