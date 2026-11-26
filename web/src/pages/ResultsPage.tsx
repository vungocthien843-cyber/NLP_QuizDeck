import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Target } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ScoreChart } from "@/features/results/ScoreChart";
import { getJSON } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AttemptSummary, Profile } from "@/lib/types";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-white p-4">
      <p className="text-xs font-medium text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
    </div>
  );
}

const MODE: Record<string, string> = { weakness: "Luyện điểm yếu" };

export function ResultsPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const profile = useQuery({ queryKey: ["profile", me?.user_id], queryFn: () => getJSON<Profile>(`/users/${me!.user_id}/profile`), enabled: !!me });
  const attempts = useQuery({ queryKey: ["my-attempts"], queryFn: () => getJSON<AttemptSummary[]>("/users/me/attempts") });

  if (profile.isPending || attempts.isPending) return <div className="grid h-full place-items-center"><Spinner /></div>;
  if (profile.isError || attempts.isError) return <p className="p-6 text-sm text-red-700">{(profile.error ?? attempts.error)?.message}</p>;
  const p = profile.data!;
  const list = attempts.data!;
  const recent = list.slice(0, 5);
  const avg = recent.length ? recent.reduce((s, a) => s + a.score_10, 0) / recent.length : null;
  const types = Object.entries(p.by_error_type).sort((a, b) => b[1] - a[1]);
  const maxType = types[0]?.[1] ?? 1;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight">Kết quả của tôi</h1>
        <p className="mt-1 text-sm text-muted">Tiến bộ qua các lần làm bài và những chỗ bạn hay hiểu nhầm.</p>

        <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tile label="Số lần làm bài" value={String(p.n_attempts)} />
          <Tile label="Số câu đã trả lời" value={String(p.n_answered)} />
          <Tile label="Tỉ lệ đúng" value={p.accuracy == null ? "—" : `${Math.round(p.accuracy * 100)}%`} />
          <Tile label="Điểm trung bình" value={avg == null ? "—" : avg.toFixed(1)} hint="5 lần gần nhất" />
        </div>

        {list.length === 0 ? (
          <div className="mt-8 rounded-xl border border-dashed border-line bg-white p-8 text-center">
            <p className="font-medium">Bạn chưa làm bài nào</p>
            <p className="mt-1 text-sm text-muted">Làm một đề ở trang Học tập, kết quả sẽ hiện ở đây.</p>
            <Button className="mt-4" onClick={() => navigate("/")}>Đến trang Học tập</Button>
          </div>
        ) : (
          <>
            <section className="mt-6 rounded-xl border border-line bg-white p-4">
              <h2 className="font-semibold">Điểm theo thời gian</h2>
              <div className="mt-3"><ScoreChart data={list} /></div>
            </section>

            <div className="mt-6 grid gap-6 lg:grid-cols-2">
              <section className="rounded-xl border border-line bg-white p-4">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="font-semibold">Chỗ bạn còn hay nhầm</h2>
                  <Button size="sm" onClick={() => navigate("/", { state: { weakness: true } })} disabled={!p.weaknesses.length}>
                    <Target className="size-3.5" /> Luyện điểm yếu
                  </Button>
                </div>
                {p.weaknesses.length === 0 ? (
                  <p className="mt-3 text-sm text-muted">Chưa đủ dữ liệu. Làm thêm vài đề để hệ thống nhận ra các kiểu hiểu nhầm của bạn.</p>
                ) : (
                  <ul className="mt-3 space-y-3">
                    {p.weaknesses.map((w) => (
                      <li key={w.concept + w.error_type} className="rounded-lg border-l-4 border-amber-500 bg-amber-50/60 p-3">
                        <p className="text-sm font-medium">{w.ten ?? w.error_type}</p>
                        <p className="mt-0.5 text-xs text-muted">Ý kiến thức: {w.concept}</p>
                        {w.chan_doan && <p className="mt-1 text-xs text-amber-900/80">{w.chan_doan}</p>}
                        <p className="mt-1 text-xs text-muted">Gặp {w.n_seen} lần</p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="rounded-xl border border-line bg-white p-4">
                <h2 className="font-semibold">Các kiểu hiểu nhầm đã gặp</h2>
                {types.length === 0 ? (
                  <p className="mt-3 text-sm text-muted">Chưa có câu sai nào gắn với một kiểu hiểu nhầm.</p>
                ) : (
                  <ul className="mt-3 space-y-2.5">
                    {types.map(([code, n]) => (
                      <li key={code}>
                        <div className="flex justify-between text-sm">
                          <span>{p.error_type_names[code] ?? code}</span>
                          <span className="tabular-nums text-muted">{n} lần</span>
                        </div>
                        <div className="mt-1 h-2 overflow-hidden rounded-full bg-brand-50">
                          <div className="h-full rounded-full bg-brand-600" style={{ width: `${(n / maxType) * 100}%` }} />
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>

            <section className="mt-6 overflow-hidden rounded-xl border border-line bg-white">
              <h2 className="p-4 font-semibold">Lịch sử làm bài</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-y border-line bg-canvas text-left text-xs text-muted">
                    <tr>
                      <th className="px-4 py-2 font-medium">Thời gian</th>
                      <th className="px-4 py-2 font-medium">Đề</th>
                      <th className="px-4 py-2 text-right font-medium">Đúng</th>
                      <th className="px-4 py-2 text-right font-medium">Điểm</th>
                      <th className="px-4 py-2"><span className="sr-only">Xem lại</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((a) => (
                      <tr key={a.attempt_id} className="border-b border-line last:border-0 hover:bg-brand-50/40">
                        <td className="whitespace-nowrap px-4 py-2.5 text-muted">{new Date(a.submitted_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })}</td>
                        <td className="px-4 py-2.5">
                          {a.label}
                          {MODE[a.mode] && <span className="ml-2 rounded bg-brand-50 px-1.5 py-0.5 text-xs text-brand-700">{MODE[a.mode]}</span>}
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums">{a.num_correct}/{a.num_questions}</td>
                        <td className="px-4 py-2.5 text-right font-semibold tabular-nums">{a.score_10.toFixed(1)}</td>
                        <td className="px-4 py-2.5 text-right">
                          <button onClick={() => navigate("/", { state: { reviewAttempt: a } })} className="inline-flex items-center gap-0.5 text-brand-700 hover:underline cursor-pointer">
                            Xem lại <ChevronRight className="size-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
