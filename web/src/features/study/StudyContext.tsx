import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { getJSON, sendJSON } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AttachedQuestion, AttemptOut, AttemptSummary, ChatMsg, Letter, Quiz, ReviewItem, ReviewOut } from "@/lib/types";

/** Đề thuộc luồng thử nghiệm 3 bước (Mốc 3): "1" = Đề 1, "2" = luyện tập, "3" = Đề 2. */
export type ExpStep = "1" | "2" | "3";

export type QuizPhase =
  | { phase: "setup" }
  | {
      phase: "taking";
      quiz: Quiz;
      label: string;
      exp?: ExpStep;
      answers: Record<number, Letter>;
      flagged: number[];
      index: number;
      deadline: number;
    }
  | { phase: "review"; quiz?: Quiz; label: string; attempt: AttemptOut; review: ReviewOut; exp?: ExpStep };

export type RightTab = "quiz" | "chat";

interface StudyState {
  docId: number | null;
  slideNo: number;
  highlight: string | null;
  viewingQuestion: number | null;
  selectDoc: (id: number | null) => void;
  goToSlide: (n: number) => void;
  /** Mở đúng slide (và tô câu trích dẫn) — dùng khi bấm trích dẫn trong phần xem lại / trợ lý. */
  openSlide: (docId: number, slideNo: number, highlight?: string | null, questionId?: number | null) => void;
  quiz: QuizPhase;
  setQuiz: (q: QuizPhase) => void;
  rightTab: RightTab;
  setRightTab: (t: RightTab) => void;
  /** Trợ lý: hội thoại hiện tại (giữ khi chuyển tab) và câu trắc nghiệm đính kèm. */
  chat: { conversationId: number | null; messages: ChatMsg[] };
  setChat: (c: { conversationId: number | null; messages: ChatMsg[] }) => void;
  attached: AttachedQuestion | null;
  setAttached: (a: AttachedQuestion | null) => void;
  askAbout: (item: ReviewItem, index: number, attemptId: number) => void;
}

const Ctx = createContext<StudyState | null>(null);

function load(key: string): QuizPhase {
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const q = JSON.parse(raw) as QuizPhase;
      if (q.phase === "taking" || q.phase === "review") return q;
    }
  } catch {
    /* trình duyệt chặn bộ nhớ: bắt đầu lại */
  }
  return { phase: "setup" };
}

export function StudyProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const storeKey = `rq.quiz.${me?.user_id ?? "anon"}`;
  const [params, setParams] = useSearchParams();
  const docId = params.get("doc") ? Number(params.get("doc")) : null;
  const slideNo = Math.max(1, Number(params.get("slide") ?? 1) || 1);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [viewingQuestion, setViewingQuestion] = useState<number | null>(null);
  const [quiz, setQuizState] = useState<QuizPhase>(() => load(storeKey));
  const [rightTab, setRightTab] = useState<RightTab>("quiz");
  const [chat, setChat] = useState<{ conversationId: number | null; messages: ChatMsg[] }>({ conversationId: null, messages: [] });
  const [attached, setAttached] = useState<AttachedQuestion | null>(null);

  // Mở lại kết quả một lần làm bài từ trang "Kết quả của tôi" (navigate("/", { state: { reviewAttempt } }))
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const st = location.state as { reviewAttempt?: AttemptSummary; weakness?: boolean } | null;
    if (st?.weakness) {
      navigate(location.pathname + location.search, { replace: true, state: null });
      sendJSON<Quiz>("/quizzes", { scope: {}, n: 10, mode: "weakness" }).then((quiz) => {
        setQuizState({ phase: "taking", quiz, label: "Luyện điểm yếu · tất cả bài", answers: {}, flagged: [], index: 0, deadline: Date.now() + quiz.questions.length * 60_000 });
        setRightTab("quiz");
      }, () => setRightTab("quiz"));
      return;
    }
    const a = st?.reviewAttempt;
    if (!a) return;
    navigate(location.pathname + location.search, { replace: true, state: null });
    getJSON<ReviewOut>(`/attempts/${a.attempt_id}/review`).then((review) => {
      setQuizState({
        phase: "review",
        label: a.label,
        attempt: { attempt_id: a.attempt_id, num_correct: a.num_correct, num_questions: a.num_questions, score_10: a.score_10 },
        review,
      });
      setRightTab("quiz");
    });
  }, [location, navigate]);

  // Lưu bài đang làm để lỡ tải lại trang / đóng tab không mất bài
  useEffect(() => {
    try {
      if (quiz.phase === "setup") localStorage.removeItem(storeKey);
      else localStorage.setItem(storeKey, JSON.stringify(quiz));
    } catch {
      /* bỏ qua */
    }
  }, [quiz, storeKey]);

  const setLoc = useCallback(
    (doc: number | null, slide: number) => {
      setParams(
        (p) => {
          const n = new URLSearchParams(p);
          if (doc == null) {
            n.delete("doc");
            n.delete("slide");
          } else {
            n.set("doc", String(doc));
            n.set("slide", String(slide));
          }
          return n;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const value = useMemo<StudyState>(
    () => ({
      docId,
      slideNo,
      highlight,
      viewingQuestion,
      selectDoc: (id) => {
        setHighlight(null);
        setViewingQuestion(null);
        setLoc(id, 1);
      },
      goToSlide: (n) => {
        setHighlight(null);
        if (docId != null) setLoc(docId, n);
      },
      openSlide: (d, s, h = null, q = null) => {
        setHighlight(h);
        setViewingQuestion(q);
        setLoc(d, s);
      },
      quiz,
      setQuiz: setQuizState,
      rightTab,
      setRightTab,
      chat,
      setChat,
      attached,
      setAttached,
      askAbout: (it, index, attemptId) => {
        setAttached({
          question_id: it.question_id,
          attempt_id: attemptId,
          index,
          stem: it.stem,
          chosen: it.chosen,
          answer: it.answer,
          is_correct: it.is_correct,
          slide_no: it.evidence_slide_no ?? it.sources[0]?.slide_no ?? null,
        });
        setRightTab("chat");
      },
    }),
    [docId, slideNo, highlight, viewingQuestion, quiz, rightTab, setLoc, chat, attached],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStudy() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useStudy phải nằm trong StudyProvider");
  return c;
}
