import { useQuery } from "@tanstack/react-query";
import { Spinner } from "@/components/ui/spinner";
import { getJSON } from "@/lib/api";
import type { ClassStats } from "@/lib/types";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-white p-4">
      <p className="text-xs font-medium text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
    </div>
  );
}

function Bars({ rows, fmt }: { rows: { label: string; value: number; note?: string }[]; fmt: (v: number) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.label}>
          <div className="flex justify-between gap-3 text-sm">
            <span className="min-w-0 truncate" title={r.label}>{r.label}</span>
            <span className="shrink-0 tabular-nums text-muted">{fmt(r.value)}{r.note ? ` · ${r.note}` : ""}</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-brand-50">
            <div className="h-full rounded-full bg-brand-600" style={{ width: `${(r.value / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Số lượt làm bài 14 ngày gần nhất: cột mảnh, nhãn ngày thưa, di chuột xem số. */
function DayChart({ days }: { days: ClassStats["attempts_by_day"] }) {
  const max = Math.max(1, ...days.map((d) => d.n_attempts));
  return (
    <div className="flex h-40 items-end gap-1.5" role="img" aria-label="Số lượt làm bài 14 ngày gần nhất">
      {days.map((d, i) => {
        const dt = new Date(d.day + "T00:00:00");
        return (
          <div key={d.day} className="group relative flex h-full flex-1 flex-col justify-end">
            <div className="rounded-t-[4px] bg-brand-600 transition-colors group-hover:bg-brand-700" style={{ height: `${Math.max(d.n_attempts ? 4 : 0, (d.n_attempts / max) * 100)}%` }} />
            <div className="h-px bg-line" />
            <span className="mt-1 h-4 text-center text-[10px] text-muted">{i % 2 === 1 || i === 13 ? `${dt.getDate()}/${dt.getMonth() + 1}` : ""}</span>
            <span className="pointer-events-none absolute -top-7 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded-md border border-line bg-white px-1.5 py-0.5 text-xs shadow group-hover:block">
              {dt.getDate()}/{dt.getMonth() + 1}: <b>{d.n_attempts}</b> lượt
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function Overview() {
  const q = useQuery({ queryKey: ["admin-stats"], queryFn: () => getJSON<ClassStats>("/admin/stats") });
  if (q.isPending) return <Spinner className="m-6" />;
  if (q.isError) return <p className="p-6 text-sm text-red-700">{q.error.message}</p>;
  const s = q.data;
  const types = Object.entries(s.by_error_type);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        <Tile label="Sinh viên" value={String(s.n_students)} />
        <Tile label="Hoạt động 7 ngày" value={String(s.n_active_7d)} hint="số người có làm bài" />
        <Tile label="Lượt làm bài" value={String(s.n_attempts)} />
        <Tile label="Tỉ lệ đúng" value={s.accuracy == null ? "—" : `${Math.round(s.accuracy * 100)}%`} hint={`${s.n_answered} câu đã trả lời`} />
        <Tile label="Bài giảng" value={String(s.n_documents)} />
        <Tile label="Câu hỏi đạt" value={String(s.n_questions)} />
      </div>
      <section className="rounded-xl border border-line bg-white p-4">
        <h2 className="mb-4 font-semibold">Lượt làm bài 14 ngày gần nhất</h2>
        <DayChart days={s.attempts_by_day} />
      </section>
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-line bg-white p-4">
          <h2 className="mb-3 font-semibold">Tỉ lệ đúng theo bài giảng</h2>
          {s.by_document.length === 0 ? <p className="text-sm text-muted">Chưa có dữ liệu.</p> : (
            <Bars fmt={(v) => `${Math.round(v * 100)}%`} rows={s.by_document.map((d) => ({ label: d.filename.replace(/\.(pptx|pdf)$/i, "").replace(/_/g, " "), value: d.accuracy ?? 0, note: `${d.n_answered} câu` }))} />
          )}
        </section>
        <section className="rounded-xl border border-line bg-white p-4">
          <h2 className="mb-3 font-semibold">Kiểu hiểu nhầm phổ biến của cả lớp</h2>
          {types.length === 0 ? <p className="text-sm text-muted">Chưa có câu sai nào gắn kiểu hiểu nhầm.</p> : (
            <Bars fmt={(v) => `${v} lần`} rows={types.map(([k, v]) => ({ label: s.error_type_names[k] ?? k, value: v }))} />
          )}
        </section>
      </div>
    </div>
  );
}
