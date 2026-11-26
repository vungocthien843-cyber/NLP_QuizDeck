import { useStudy } from "../study/StudyContext";
import { QuizReview } from "./QuizReview";
import { QuizSetup } from "./QuizSetup";
import { QuizTaking } from "./QuizTaking";

export function QuizPanel() {
  const { quiz } = useStudy();
  if (quiz.phase === "taking") return <QuizTaking s={quiz} />;
  if (quiz.phase === "review") return <QuizReview s={quiz} />;
  return (
    <div className="h-full overflow-y-auto">
      <QuizSetup />
    </div>
  );
}
