import { useState } from "react";
import type { AttemptSummary } from "@/lib/types";

/** Điểm các lần làm bài theo thời gian: một chuỗi, nét mảnh, lưới nhạt, di chuột để xem chi tiết. */
export function ScoreChart({ data }: { data: AttemptSummary[] }) {
  const pts = [...data].reverse().slice(-20);
  const [hover, setHover] = useState<number | null>(null);
  const W = 640, H = 200, L = 32, R = 12, T = 12, B = 24;
  const x = (i: number) => L + (pts.length <= 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (pts.length - 1));
  const y = (v: number) => T + ((10 - v) * (H - T - B)) / 10;
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.score_10)}`).join(" ");
  const h = hover != null ? pts[hover] : null;
  return (
    <figure className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Điểm ${pts.length} lần làm bài gần nhất`} onMouseLeave={() => setHover(null)}>
        {[0, 5, 10].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--color-line)" strokeDasharray={v ? "3 4" : undefined} />
            <text x={L - 8} y={y(v) + 4} textAnchor="end" fontSize="9" fill="var(--color-muted)">{v}</text>
          </g>
        ))}
        <path d={path} fill="none" stroke="var(--color-brand-600)" strokeWidth="2" strokeLinejoin="round" />
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} stroke="var(--color-brand-200)" />}
        {pts.map((p, i) => (
          <g key={p.attempt_id}>
            <circle cx={x(i)} cy={y(p.score_10)} r={hover === i ? 5 : 4} fill="white" stroke="var(--color-brand-600)" strokeWidth="2" />
            <rect x={x(i) - 14} y={T} width={28} height={H - T - B} fill="transparent" onMouseEnter={() => setHover(i)} />
          </g>
        ))}
        <text x={L} y={H - 6} fontSize="9" fill="var(--color-muted)">Cũ hơn</text>
        <text x={W - R} y={H - 6} fontSize="9" fill="var(--color-muted)" textAnchor="end">Gần nhất</text>
      </svg>
      {h && hover != null && (
        <div className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-lg border border-line bg-white px-2.5 py-1.5 text-xs shadow-md" style={{ left: `${(x(hover) / W) * 100}%` }}>
          <p className="font-semibold tabular-nums">{h.score_10.toFixed(1)} điểm · {h.num_correct}/{h.num_questions} câu</p>
          <p className="text-muted">{new Date(h.submitted_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })}</p>
          <p className="max-w-48 truncate text-muted">{h.label}</p>
        </div>
      )}
    </figure>
  );
}
