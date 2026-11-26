/** Luồng thử nghiệm 3 bước với sinh viên (Mốc 3): Đề 1 → Luyện tập → Đề 2, kèm khảo sát ngắn.
 * Chỉ hiện khi đang mở thử nghiệm và email của sinh viên có trong danh sách. Không cho sinh viên biết mình ở nhóm nào. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle, CircleDot, FlaskConical } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { getJSON, sendJSON } from "@/lib/api";
import type { ExperimentState, Quiz } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type ExpStep, useStudy } from "../study/StudyContext";

const LIKERT = [1, 2, 3, 4, 5];

export function useExperiment() {
  const q = useQuery({ queryKey: ["experiment"], queryFn: () => getJSON<ExperimentState>("/experiment/state"), staleTime: 30_000 });
  return q.data?.active && q.data.member ? q.data : null;
}

function useFeedback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { attempt_id: number; kind: string; value?: number | null; question_id?: number | null; comment?: string | null }) =>
      sendJSON("/feedback", b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["experiment"] }),
  });
}

function Likert({ label, value, onChange }: { label: string; value: number | null; onChange: (v: number) => void }) {
  return (
    <fieldset>
      <legend className="text-sm">{label}</legend>
      <div className="mt-2 flex gap-1.5">
        {LIKERT.map((v) => (
          <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)} className={cn("h-9 flex-1 rounded-lg border text-sm font-medium cursor-pointer", value === v ? "border-brand-600 bg-brand-600 text-white" : "border-line bg-white hover:border-brand-200")}>
            {v}
          </button>
        ))}
      </div>
      <p className="mt-1 flex justify-between text-[11px] text-muted"><span>Hoàn toàn không</span><span>Hoàn toàn đúng</span></p>
    </fieldset>
  );
}

export function OverallSurvey({ attemptId }: { attemptId: number }) {
  const fb = useFeedback();
  const [d, setD] = useState<number | null>(null);
  const [e, setE] = useState<number | null>(null);
  return (
    <div className="space-y-4 rounded-xl border border-brand-200 bg-brand-50/50 p-4">
      <Likert label="Phần “Có thể bạn đang nhầm” nhìn chung có đúng với điều bạn đã nghĩ khi chọn sai không?" value={d} onChange={setD} />
      <Likert label="Lời giải thích và trích dẫn slide có giúp bạn hiểu bài hơn không?" value={e} onChange={setE} />
      {fb.isError && <p className="text-sm text-red-700">{fb.error.message}</p>}
      <Button className="w-full" disabled={d == null || e == null || fb.isPending} onClick={async () => {
        await fb.mutateAsync({ attempt_id: attemptId, kind: "diag_overall", value: d });
        await fb.mutateAsync({ attempt_id: attemptId, kind: "explain_overall", value: e });
      }}>Gửi khảo sát</Button>
    </div>
  );
}

/** Khung 3 bước ở đầu phần tạo đề. Trả true khi sinh viên đang giữa thử nghiệm (ẩn phần tạo đề tự do). */
export function ExperimentBox({ ex }: { ex: ExperimentState }) {
  const { setQuiz } = useStudy();
  const [err, setErr] = useState<string | null>(null);
  const step = ex.step;
  const start = async (exp: ExpStep, load: () => Promise<Quiz>, label: string) => {
    setErr(null);
    try {
      const quiz = await load();
      setQuiz({ phase: "taking", quiz: { ...quiz, notice: null }, label, exp, answers: {}, flagged: [], index: 0, deadline: Date.now() + quiz.questions.length * 60_000 });
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const steps = [
    { k: "1", t: "Làm Đề 1" },
    { k: "2", t: `Luyện tập (${ex.practice_n ?? 10} câu)` },
    { k: "3", t: "Làm Đề 2" },
  ];
  const a1 = String(ex.attempt1_id);
  const surveyed = ["diag_overall", "explain_overall"].every((k) => ex.feedback_kinds[a1]?.includes(k));

  return (
    <div className="rounded-xl border border-brand-200 bg-white p-4">
      <p className="flex items-center gap-2 font-semibold"><FlaskConical className="size-4 text-brand-600" /> Thử nghiệm hệ thống ôn tập</p>
      <ol className="mt-3 space-y-1.5 text-sm">
        {steps.map((s) => {
          const done = step === "done" || (step != null && s.k < step);
          const cur = s.k === step;
          return (
            <li key={s.k} className={cn("flex items-center gap-2", cur ? "font-medium text-brand-800" : done ? "text-muted" : "text-muted/70")}>
              {done ? <CheckCircle2 className="size-4 text-emerald-600" /> : cur ? <CircleDot className="size-4 text-brand-600" /> : <Circle className="size-4" />}
              Bước {s.k} · {s.t}
            </li>
          );
        })}
      </ol>
      <div className="mt-4">
        {step === "1" && (
          <>
            <p className="mb-3 text-xs text-muted">Làm bài nghiêm túc, không xem slide hay tài liệu. Sau khi nộp, xem lại các câu sai và trả lời khảo sát ngắn.</p>
            <Button className="w-full" onClick={() => start("1", () => getJSON<Quiz>(`/quizzes/${ex.quiz1_id}`), "Thử nghiệm · Đề 1")}>Bắt đầu Đề 1</Button>
          </>
        )}
        {step === "2" && !surveyed && ex.attempt1_id && (
          <>
            <p className="mb-3 text-xs text-muted">Trước khi luyện tập, hãy trả lời 2 câu khảo sát về Đề 1:</p>
            <OverallSurvey attemptId={ex.attempt1_id} />
          </>
        )}
        {step === "2" && surveyed && (
          <>
            {ex.practice_quiz_id && <p className="mb-2 text-xs text-muted">Bạn có một đề luyện tập đang làm dở.</p>}
            <Button className="w-full" onClick={() => start("2", () => sendJSON<Quiz>("/experiment/practice", {}), "Thử nghiệm · Luyện tập")}>Bắt đầu luyện tập</Button>
          </>
        )}
        {step === "3" && (
          <>
            <p className="mb-3 text-xs text-muted">Bước cuối. Làm bài nghiêm túc như Đề 1.</p>
            <Button className="w-full" onClick={() => start("3", () => getJSON<Quiz>(`/quizzes/${ex.quiz2_id}`), "Thử nghiệm · Đề 2")}>Bắt đầu Đề 2</Button>
          </>
        )}
        {step === "done" && <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">Bạn đã hoàn thành thử nghiệm. Cảm ơn bạn! Bạn có thể tiếp tục tự ôn tập bên dưới.</p>}
        {err && <p role="alert" className="mt-2 text-sm text-red-700">{err}</p>}
      </div>
    </div>
  );
}

/** Khảo sát ở đầu trang kết quả của từng bước thử nghiệm. */
export function ReviewSurvey({ exp, attemptId }: { exp: ExpStep; attemptId: number }) {
  const ex = useExperiment();
  const fb = useFeedback();
  const [v, setV] = useState<number | null>(null);
  const [text, setText] = useState("");
  if (!ex) return null;
  const done = new Set(ex.feedback_kinds[String(attemptId)] ?? []);
  if (exp === "1")
    return (
      <div className="space-y-3">
        <p className="rounded-lg bg-brand-50 p-3 text-xs text-brand-900">Ở mỗi câu sai có chẩn đoán, hãy cho biết chẩn đoán có đúng với điều bạn đã nghĩ không. Sau đó trả lời 2 câu khảo sát bên dưới.</p>
        {done.has("diag_overall") && done.has("explain_overall") ? (
          <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">Đã ghi khảo sát Đề 1. Cảm ơn bạn! Bấm “Làm đề mới” để sang bước Luyện tập.</p>
        ) : (
          <OverallSurvey attemptId={attemptId} />
        )}
      </div>
    );
  if (exp === "2" && !done.has("practice_useful"))
    return (
      <div className="space-y-3 rounded-xl border border-brand-200 bg-brand-50/50 p-4">
        <Likert label="Đề luyện tập này có giúp bạn ôn đúng chỗ còn yếu không?" value={v} onChange={setV} />
        <Button className="w-full" disabled={v == null || fb.isPending} onClick={() => fb.mutate({ attempt_id: attemptId, kind: "practice_useful", value: v })}>Gửi</Button>
      </div>
    );
  if (exp === "3" && !done.has("comment"))
    return (
      <div className="space-y-3 rounded-xl border border-brand-200 bg-brand-50/50 p-4">
        <label className="block text-sm" htmlFor="exp-comment">Góp ý của bạn về hệ thống (không bắt buộc)</label>
        <textarea id="exp-comment" maxLength={2000} rows={3} value={text} onChange={(e) => setText(e.target.value)} className="w-full rounded-lg border border-line p-2 text-sm outline-none focus:border-brand-500" />
        <Button className="w-full" disabled={fb.isPending} onClick={() => fb.mutate({ attempt_id: attemptId, kind: "comment", comment: text.trim() || "(không góp ý)" })}>Gửi góp ý</Button>
      </div>
    );
  return null;
}

const DIAG = [
  { label: "Đúng", value: 2 },
  { label: "Một phần", value: 1 },
  { label: "Không đúng", value: 0 },
];

/** Đề 1: hỏi chẩn đoán của từng câu sai có đúng ý sinh viên không. */
export function ItemFeedback({ attemptId, questionId }: { attemptId: number; questionId: number }) {
  const fb = useFeedback();
  const [v, setV] = useState<number | null>(null);
  return (
    <fieldset className="mt-2">
      <legend className="text-xs text-muted">Chẩn đoán này có đúng với điều bạn đã nghĩ khi chọn?</legend>
      <div className="mt-1 flex gap-1.5">
        {DIAG.map((d) => (
          <button key={d.value} type="button" aria-pressed={v === d.value} onClick={() => { setV(d.value); fb.mutate({ attempt_id: attemptId, kind: "diag_item", value: d.value, question_id: questionId }); }} className={cn("rounded-full border px-2.5 py-0.5 text-xs cursor-pointer", v === d.value ? "border-amber-600 bg-amber-600 text-white" : "border-amber-300 bg-white text-amber-900 hover:bg-amber-100")}>
            {d.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
