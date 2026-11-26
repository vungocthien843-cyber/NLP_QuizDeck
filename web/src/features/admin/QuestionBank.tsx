import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Segmented } from "@/components/ui/segmented";
import { Spinner } from "@/components/ui/spinner";
import { getJSON } from "@/lib/api";
import { BLOOM_VI, docTitle } from "@/lib/format";
import type { BankQuestion, DocumentInfo, Letter } from "@/lib/types";
import { cn } from "@/lib/utils";

const DIFF_VI: Record<string, string> = { easy: "Dễ", medium: "Vừa", hard: "Khó" };
const LETTERS: Letter[] = ["A", "B", "C", "D"];

export function QuestionBank({ doc, names, onBack }: { doc: DocumentInfo; names: Record<string, string>; onBack: () => void }) {
  const q = useQuery({ queryKey: ["bank", doc.id], queryFn: () => getJSON<BankQuestion[]>(`/admin/documents/${doc.id}/questions`) });
  const [status, setStatus] = useState<"accepted" | "rejected" | "all">("accepted");
  const [bloom, setBloom] = useState<"all" | "remember" | "understand" | "apply">("all");
  const [kw, setKw] = useState("");
  const list = useMemo(() => {
    const k = kw.trim().toLowerCase();
    return (q.data ?? []).filter((x) => (status === "all" || x.status === status) && (bloom === "all" || x.bloom_level === bloom) && (!k || x.stem.toLowerCase().includes(k)));
  }, [q.data, status, bloom, kw]);
  const nAcc = q.data?.filter((x) => x.status === "accepted").length ?? 0;
  const nRej = (q.data?.length ?? 0) - nAcc;

  return (
    <div>
      <button onClick={onBack} className="inline-flex items-center gap-1 text-sm text-brand-700 hover:underline cursor-pointer"><ArrowLeft className="size-4" /> Danh sách bài giảng</button>
      <h2 className="mt-2 text-lg font-semibold">Ngân hàng câu hỏi · {docTitle(doc)}</h2>
      <div className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_1fr]">
        <Segmented label="Trạng thái" value={status} onChange={setStatus} options={[{ value: "accepted", label: `Đạt (${nAcc})` }, { value: "rejected", label: `Bị loại (${nRej})` }, { value: "all", label: "Tất cả" }]} />
        <Segmented label="Mức Bloom" value={bloom} onChange={setBloom} options={[{ value: "all", label: "Mọi mức" }, { value: "remember", label: "Nhớ" }, { value: "understand", label: "Hiểu" }, { value: "apply", label: "Vận dụng" }]} />
        <label className="relative block">
          <span className="sr-only">Tìm câu hỏi</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="Tìm trong câu hỏi…" className="h-9 w-full rounded-lg border border-line bg-white pl-8 pr-3 text-sm outline-none focus:border-brand-500" />
        </label>
      </div>
      {q.isPending && <Spinner className="m-6" />}
      {q.isError && <p className="mt-4 text-sm text-red-700">{q.error.message}</p>}
      {q.data && <p className="mt-4 text-sm text-muted">{list.length} câu</p>}
      <ul className="mt-2 space-y-3">
        {list.map((x) => (
          <li key={x.question_id} className={cn("rounded-xl border bg-white p-4", x.status === "rejected" ? "border-red-200" : "border-line")}>
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-muted">#{x.question_id}</span>
              {x.bloom_level && <span className="rounded bg-brand-50 px-1.5 py-0.5 text-brand-700">{BLOOM_VI[x.bloom_level] ?? x.bloom_level}</span>}
              {x.difficulty && <span className="rounded bg-canvas px-1.5 py-0.5 ring-1 ring-line">{DIFF_VI[x.difficulty] ?? x.difficulty}</span>}
              {x.slide_no && <span className="rounded bg-canvas px-1.5 py-0.5 ring-1 ring-line">Slide {x.slide_no}</span>}
              {x.concept && <span className="max-w-64 truncate text-muted" title={x.concept}>· {x.concept}</span>}
              <span className="ml-auto text-muted">{x.n_answered ? `${x.n_answered} lượt trả lời · đúng ${Math.round((x.accuracy ?? 0) * 100)}%` : "Chưa ai làm"}</span>
            </div>
            {x.status === "rejected" && <p className="mt-2 rounded-md bg-red-50 px-2 py-1 text-xs text-red-800">Bị loại: {x.reject_reason ?? "không rõ lý do"}</p>}
            <p className="mt-2 text-sm font-medium">{x.stem}</p>
            <ul className="mt-2 space-y-1">
              {LETTERS.filter((l) => x.options[l] != null).map((l) => (
                <li key={l} className={cn("flex items-start gap-2 rounded-md px-2 py-1 text-sm", l === x.answer && "bg-emerald-50")}>
                  <span className={cn("grid size-5 shrink-0 place-items-center rounded text-[11px] font-semibold", l === x.answer ? "bg-emerald-600 text-white" : "bg-canvas text-muted ring-1 ring-line")}>{l}</span>
                  <span className="flex-1">{x.options[l]}</span>
                  {l !== x.answer && x.error_types[l] && <span className="shrink-0 rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-800">{names[x.error_types[l]!] ?? x.error_types[l]}</span>}
                </li>
              ))}
            </ul>
            {x.explanation && <p className="mt-2 text-xs leading-relaxed text-muted"><b className="text-ink">Giải thích:</b> {x.explanation}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
