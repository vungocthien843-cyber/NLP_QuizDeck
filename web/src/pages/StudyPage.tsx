import { BookOpen, ClipboardList, MessagesSquare, PanelLeftOpen, Presentation } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ChatPanel } from "@/features/chat/ChatPanel";
import { QuizPanel } from "@/features/quiz/QuizPanel";
import { LibraryPanel } from "@/features/study/LibraryPanel";
import { SlideViewer } from "@/features/study/SlideViewer";
import { StudyProvider, useStudy } from "@/features/study/StudyContext";
import { cn } from "@/lib/utils";

function RightPanel() {
  const { rightTab, setRightTab, quiz } = useStudy();
  const badge = quiz.phase === "taking" ? "đang làm" : quiz.phase === "review" ? "kết quả" : null;
  const tabs = [
    { key: "quiz" as const, label: "Trắc nghiệm", icon: ClipboardList, badge },
    { key: "chat" as const, label: "Trợ lý", icon: MessagesSquare, badge: null },
  ];
  return (
    <div className="flex h-full flex-col">
      <div role="tablist" aria-label="Công cụ" className="flex gap-1 border-b border-line px-2 pt-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={rightTab === t.key}
            onClick={() => setRightTab(t.key)}
            className={cn(
              "flex items-center gap-1.5 rounded-t-lg border-b-2 px-3 py-2 text-sm font-medium cursor-pointer",
              rightTab === t.key ? "border-brand-600 text-brand-700" : "border-transparent text-muted hover:text-ink",
            )}
          >
            <t.icon className="size-4" />
            {t.label}
            {t.badge && <span className="rounded bg-brand-50 px-1.5 text-[11px] text-brand-700">{t.badge}</span>}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="min-h-0 flex-1">
        {rightTab === "quiz" ? <QuizPanel /> : <ChatPanel />}
      </div>
    </div>
  );
}

type MobileTab = "library" | "slide" | "tools";

function Workspace() {
  const { quiz, docId, highlight } = useStudy();
  const [leftOpen, setLeftOpen] = useState(true);
  const [mobile, setMobile] = useState<MobileTab>(docId ? "slide" : "library");
  // Màn hình hẹp: chọn bài hoặc bấm "Xem trên slide" thì chuyển sang tab Slide
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (docId) setMobile("slide");
  }, [docId, highlight]);
  const wide = quiz.phase !== "setup";

  const mobileTabs: { key: MobileTab; label: string; icon: typeof BookOpen }[] = [
    { key: "library", label: "Bài giảng", icon: BookOpen },
    { key: "slide", label: "Slide", icon: Presentation },
    { key: "tools", label: "Ôn tập", icon: ClipboardList },
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="flex border-b border-line bg-white lg:hidden" role="tablist">
        {mobileTabs.map((t) => (
          <button key={t.key} role="tab" aria-selected={mobile === t.key} onClick={() => setMobile(t.key)} className={cn("flex flex-1 items-center justify-center gap-1.5 border-b-2 py-2 text-sm cursor-pointer", mobile === t.key ? "border-brand-600 font-medium text-brand-700" : "border-transparent text-muted")}>
            <t.icon className="size-4" /> {t.label}
          </button>
        ))}
      </div>
      <div className="flex min-h-0 flex-1">
        <aside className={cn("relative shrink-0 border-r border-line bg-white", leftOpen ? "lg:w-72" : "lg:w-12", mobile === "library" ? "w-full" : "hidden", "lg:block")}>
          {!leftOpen && (
            <button onClick={() => setLeftOpen(true)} aria-label="Mở danh sách bài" className="mx-auto mt-3 hidden rounded p-1.5 text-muted hover:bg-brand-50 lg:block cursor-pointer">
              <PanelLeftOpen className="size-4" />
            </button>
          )}
          <div className={cn("h-full", !leftOpen && "lg:hidden")}>
            <LibraryPanel onCollapse={() => setLeftOpen(false)} />
          </div>
        </aside>
        <section aria-label="Slide" className={cn("min-w-0 flex-1 bg-canvas", mobile === "slide" ? "block" : "hidden", "lg:block")}>
          <SlideViewer />
        </section>
        <aside className={cn("shrink-0 border-l border-line bg-white", wide ? "lg:w-[30rem]" : "lg:w-[24rem]", mobile === "tools" ? "w-full" : "hidden", "lg:block")}>
          <RightPanel />
        </aside>
      </div>
    </div>
  );
}

export function StudyPage() {
  return (
    <StudyProvider>
      <Workspace />
    </StudyProvider>
  );
}
