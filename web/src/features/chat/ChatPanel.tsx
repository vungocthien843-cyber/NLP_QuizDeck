import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Lock, MessageSquarePlus, Paperclip, SendHorizontal, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Spinner } from "@/components/ui/spinner";
import { getJSON, request } from "@/lib/api";
import type { ChatCitation, ChatMsg, ConversationInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useStudy } from "../study/StudyContext";

const SUGGESTIONS = ["Tóm tắt các ý chính của bài học", "Giải thích một khái niệm khó trong bài", "Cho ví dụ minh họa dễ hiểu"];

/** Biến [1] trong câu trả lời thành liên kết bấm được tới nguồn tương ứng. */
function linkCitations(text: string, cites: ChatCitation[]) {
  const ok = new Set(cites.map((c) => c.n));
  return text.replace(/\[(\d+)\]/g, (m, n) => (ok.has(Number(n)) ? `[[${n}]](#cite-${n})` : m));
}

function Answer({ m }: { m: ChatMsg }) {
  const { openSlide } = useStudy();
  const open = (c: ChatCitation) => openSlide(c.document_id, c.slide_no ?? 1);
  return (
    <div className="text-sm leading-relaxed">
      <div className="prose-chat">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => {
              const n = href?.startsWith("#cite-") ? Number(href.slice(6)) : null;
              const c = n != null ? m.citations.find((x) => x.n === n) : null;
              if (c)
                return (
                  <button onClick={() => open(c)} title={`Mở slide ${c.slide_no}`} className="mx-0.5 rounded bg-brand-50 px-1 text-xs font-semibold text-brand-700 hover:bg-brand-100 cursor-pointer">
                    {children}
                  </button>
                );
              return <a href={href} target="_blank" rel="noreferrer noopener" className="text-brand-700 underline">{children}</a>;
            },
          }}
        >
          {linkCitations(m.content, m.citations)}
        </ReactMarkdown>
      </div>
      {m.pending && !m.content && <Spinner className="size-4" />}
      {m.error && <p className="mt-2 rounded-md bg-red-50 p-2 text-xs text-red-700">Không nhận được câu trả lời: {m.error}</p>}
      {m.citations.length > 0 && (
        <div className="mt-3 space-y-1">
          <p className="text-xs font-semibold text-muted">Nguồn</p>
          {m.citations.map((c) => (
            <button key={c.n} onClick={() => open(c)} className="flex w-full items-start gap-2 rounded-md border border-line bg-white px-2 py-1.5 text-left text-xs hover:border-brand-200 hover:bg-brand-50 cursor-pointer">
              <span className="font-semibold text-brand-700">[{c.n}]</span>
              <span className="min-w-0 flex-1 truncate">
                {(c.filename ?? "Tài liệu").replace(/_/g, " ")} · Slide {c.slide_no}
                {c.title ? ` · ${c.title}` : ""}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Bubble({ m }: { m: ChatMsg }) {
  if (m.role === "user")
    return (
      <div className="ml-8 rounded-2xl rounded-br-sm bg-brand-600 px-3 py-2 text-sm text-white">
        {m.attach && <p className="mb-1 border-l-2 border-white/50 pl-2 text-xs text-brand-100">Câu {m.attach.index + 1} · {m.attach.stem}</p>}
        <p className="whitespace-pre-wrap">{m.content}</p>
      </div>
    );
  return (
    <div className="mr-4">
      <p className="mb-1 flex items-center gap-1 text-xs font-semibold text-muted">
        <Sparkles className="size-3 text-brand-600" /> Trợ lý học tập
      </p>
      <Answer m={m} />
    </div>
  );
}

function HistoryMenu({ onPick, children }: { onPick: (id: number) => void; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const convs = useQuery({ queryKey: ["conversations"], queryFn: () => getJSON<ConversationInfo[]>("/chat/conversations"), enabled: open });
  return (
    <div className="relative">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="rounded p-1.5 text-muted hover:bg-brand-50 hover:text-ink cursor-pointer" title="Hội thoại cũ">
        {children}
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 max-h-80 w-72 overflow-y-auto rounded-xl border border-line bg-white p-1 shadow-lg">
          {convs.isPending && <Spinner className="m-3" />}
          {convs.data?.length === 0 && <p className="p-3 text-sm text-muted">Chưa có hội thoại nào.</p>}
          {convs.data?.map((c) => (
            <button key={c.conversation_id} onClick={() => { setOpen(false); onPick(c.conversation_id); }} className="block w-full rounded-lg px-3 py-2 text-left hover:bg-brand-50 cursor-pointer">
              <span className="line-clamp-1 text-sm">{c.title}</span>
              <span className="text-xs text-muted">{new Date(c.created_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })} · {c.n_messages} tin</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function ChatPanel() {
  const { quiz, chat, setChat, attached, setAttached } = useStudy();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [chat.messages]);
  useEffect(() => {
    if (attached) input.current?.focus();
  }, [attached]);

  if (quiz.phase === "taking")
    return (
      <div className="grid h-full place-items-center p-6 text-center text-sm text-muted">
        <div>
          <Lock className="mx-auto size-6 text-brand-600" />
          <p className="mt-2">Trợ lý tạm khóa trong lúc làm bài. Nộp bài xong bạn có thể hỏi về từng câu, kể cả câu làm sai.</p>
        </div>
      </div>
    );

  const send = async (msg: string) => {
    msg = msg.trim();
    if (!msg || busy) return;
    const att = attached;
    const base = [...chat.messages, { role: "user" as const, content: msg, citations: [], attach: att }];
    let answer: ChatMsg = { role: "assistant", content: "", citations: [], pending: true };
    let conv = chat.conversationId;
    const push = () => setChat({ conversationId: conv, messages: [...base, answer] });
    setText("");
    setAttached(null);
    setBusy(true);
    stick.current = true;
    push();
    try {
      const res = await request("/chat", {
        method: "POST",
        body: JSON.stringify({ message: msg, conversation_id: conv, question_id: att?.question_id ?? null, attempt_id: att?.attempt_id ?? null }),
      });
      conv = Number(res.headers.get("X-Conversation-Id")) || conv;
      const reader = res.body!.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.type === "token") answer = { ...answer, content: answer.content + ev.text };
          else if (ev.type === "done") answer = { ...answer, citations: ev.citations ?? [] };
          else if (ev.type === "error") answer = { ...answer, error: ev.message };
        }
        push();
      }
      if (!answer.content && !answer.error) answer = { ...answer, error: "Mô hình trả về nội dung rỗng." };
    } catch (e) {
      answer = { ...answer, error: (e as Error).message };
    } finally {
      answer = { ...answer, pending: false };
      push();
      setBusy(false);
      qc.invalidateQueries({ queryKey: ["conversations"] });
    }
  };

  const openConversation = async (id: number) => {
    const msgs = await getJSON<ChatMsg[]>(`/chat/conversations/${id}`);
    setAttached(null);
    setChat({ conversationId: id, messages: msgs });
  };

  const tips = attached ? [...(attached.is_correct ? [] : [`Vì sao chọn ${attached.chosen ?? "đáp án đó"} là sai?`]), "Giải thích kỹ hơn bằng ví dụ", "Cho mình một câu tương tự để luyện"] : [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b border-line px-3 py-2">
        <p className="mr-auto text-xs text-muted">Trả lời dựa trên slide bạn được xem, luôn kèm nguồn.</p>
        <HistoryMenu onPick={openConversation}>
          <History className="size-4" />
        </HistoryMenu>
        <button onClick={() => { setChat({ conversationId: null, messages: [] }); setAttached(null); }} disabled={!chat.messages.length || busy} className="rounded p-1.5 text-muted hover:bg-brand-50 hover:text-ink disabled:opacity-30 cursor-pointer" title="Hội thoại mới">
          <MessageSquarePlus className="size-4" />
        </button>
      </div>

      <div ref={scroller} onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }} className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite">
        {chat.messages.length === 0 && !attached && (
          <div className="pt-6 text-center">
            <Sparkles className="mx-auto size-7 text-brand-500" />
            <p className="mt-2 font-medium">Hỏi đáp về bài giảng</p>
            <p className="mt-1 text-sm text-muted">Bấm vào số [1], [2] trong câu trả lời để mở đúng slide làm căn cứ.</p>
            <div className="mt-4 space-y-2">
              {SUGGESTIONS.map((sg) => (
                <button key={sg} onClick={() => send(sg)} className="block w-full rounded-lg border border-line px-3 py-2 text-left text-sm hover:border-brand-200 hover:bg-brand-50 cursor-pointer">{sg}</button>
              ))}
            </div>
          </div>
        )}
        {chat.messages.map((m, i) => <Bubble key={i} m={m} />)}
      </div>

      <div className="border-t border-line p-3">
        {attached && (
          <div className="mb-2 rounded-lg border border-brand-200 bg-brand-50 p-2.5 text-xs">
            <div className="flex items-start gap-2">
              <Paperclip className="mt-0.5 size-3.5 shrink-0 text-brand-700" />
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-brand-800">Đính kèm · Câu {attached.index + 1} ({attached.is_correct ? "đúng" : "sai"})</p>
                <p className="line-clamp-2">{attached.stem}</p>
                <p className="mt-0.5 text-muted">Bạn chọn {attached.chosen ?? "—"} · Đáp án đúng {attached.answer}{attached.slide_no ? ` · Slide ${attached.slide_no}` : ""}</p>
              </div>
              <button onClick={() => setAttached(null)} aria-label="Bỏ đính kèm" className="rounded p-0.5 hover:bg-brand-100 cursor-pointer"><X className="size-3.5" /></button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {tips.map((t) => (
                <button key={t} onClick={() => send(t)} className="rounded-full border border-brand-200 bg-white px-2 py-0.5 hover:bg-brand-100 cursor-pointer">{t}</button>
              ))}
            </div>
          </div>
        )}
        <form onSubmit={(e) => { e.preventDefault(); send(text); }} className="flex items-end gap-2">
          <label className="sr-only" htmlFor="chat-input">Câu hỏi</label>
          <textarea
            id="chat-input"
            ref={input}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(text); } }}
            placeholder={attached ? "Hỏi về câu trắc nghiệm này…" : "Đặt câu hỏi về nội dung bài giảng…"}
            className="max-h-32 min-h-10 flex-1 resize-none rounded-lg border border-line px-3 py-2 text-sm outline-none [field-sizing:content] focus:border-brand-500"
          />
          <button type="submit" disabled={!text.trim() || busy} aria-label="Gửi" className={cn("grid size-10 place-items-center rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-40 cursor-pointer")}>
            {busy ? <Spinner className="size-4 border-white/40 border-t-white" /> : <SendHorizontal className="size-4" />}
          </button>
        </form>
      </div>
    </div>
  );
}
