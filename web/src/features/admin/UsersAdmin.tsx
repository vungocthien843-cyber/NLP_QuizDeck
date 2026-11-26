import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Spinner } from "@/components/ui/spinner";
import { Avatar } from "@/components/UserMenu";
import { ScoreChart } from "@/features/results/ScoreChart";
import { getJSON } from "@/lib/api";
import type { AttemptSummary, Me, Profile, UserRow } from "@/lib/types";

const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const asMe = (u: UserRow) => ({ user_id: u.user_id, email: u.email, name: u.name, avatar_url: u.avatar_url, is_admin: u.is_admin, csrf_token: "" }) as Me;

function Detail({ u, onBack }: { u: UserRow; onBack: () => void }) {
  const profile = useQuery({ queryKey: ["admin-profile", u.user_id], queryFn: () => getJSON<Profile>(`/users/${u.user_id}/profile`) });
  const atts = useQuery({ queryKey: ["admin-attempts", u.user_id], queryFn: () => getJSON<AttemptSummary[]>(`/admin/users/${u.user_id}/attempts`) });
  return (
    <div>
      <button onClick={onBack} className="inline-flex items-center gap-1 text-sm text-brand-700 hover:underline cursor-pointer"><ArrowLeft className="size-4" /> Danh sách sinh viên</button>
      <div className="mt-3 flex items-center gap-3">
        <Avatar me={asMe(u)} className="size-12" />
        <div>
          <p className="text-lg font-semibold">{u.name ?? u.email}</p>
          <p className="text-sm text-muted">{u.email} · {u.n_attempts} lần làm bài · tỉ lệ đúng {pct(u.accuracy)}</p>
        </div>
      </div>
      {(profile.isPending || atts.isPending) && <Spinner className="m-6" />}
      {atts.data && atts.data.length > 0 && (
        <section className="mt-5 rounded-xl border border-line bg-white p-4">
          <h3 className="font-semibold">Điểm theo thời gian</h3>
          <ScoreChart data={atts.data} />
        </section>
      )}
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-line bg-white p-4">
          <h3 className="font-semibold">Chỗ còn hay nhầm</h3>
          {profile.data?.weaknesses.length === 0 && <p className="mt-2 text-sm text-muted">Chưa đủ dữ liệu.</p>}
          <ul className="mt-2 space-y-2">
            {profile.data?.weaknesses.map((w) => (
              <li key={w.concept + w.error_type} className="rounded-lg border-l-4 border-amber-500 bg-amber-50/60 p-2.5 text-sm">
                <b className="font-medium">{w.ten ?? w.error_type}</b>
                <p className="text-xs text-muted">Ý kiến thức: {w.concept} · gặp {w.n_seen} lần</p>
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-xl border border-line bg-white p-4">
          <h3 className="font-semibold">Lịch sử làm bài</h3>
          {atts.data?.length === 0 && <p className="mt-2 text-sm text-muted">Chưa làm bài nào.</p>}
          <ul className="mt-2 divide-y divide-line">
            {atts.data?.map((a) => (
              <li key={a.attempt_id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="min-w-0">
                  <span className="block truncate">{a.label}{a.mode === "weakness" && <span className="ml-1.5 rounded bg-brand-50 px-1 text-xs text-brand-700">Luyện điểm yếu</span>}</span>
                  <span className="text-xs text-muted">{new Date(a.submitted_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })}</span>
                </span>
                <span className="shrink-0 tabular-nums"><b>{a.score_10.toFixed(1)}</b> <span className="text-muted">({a.num_correct}/{a.num_questions})</span></span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

export function UsersAdmin() {
  const q = useQuery({ queryKey: ["admin-users"], queryFn: () => getJSON<UserRow[]>("/admin/users") });
  const [kw, setKw] = useState("");
  const [sel, setSel] = useState<UserRow | null>(null);
  const list = useMemo(() => {
    const k = kw.trim().toLowerCase();
    return (q.data ?? []).filter((u) => !k || (u.email ?? "").toLowerCase().includes(k) || (u.name ?? "").toLowerCase().includes(k));
  }, [q.data, kw]);
  if (sel) return <Detail u={sel} onBack={() => setSel(null)} />;
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">{q.data?.length ?? 0} tài khoản</p>
        <label className="relative block w-72">
          <span className="sr-only">Tìm sinh viên</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="Tìm theo tên hoặc email…" className="h-9 w-full rounded-lg border border-line bg-white pl-8 pr-3 text-sm outline-none focus:border-brand-500" />
        </label>
      </div>
      {q.isPending && <Spinner className="m-6" />}
      {q.isError && <p className="mt-3 text-sm text-red-700">{q.error.message}</p>}
      <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-white">
        <table className="w-full text-sm">
          <thead className="border-b border-line bg-canvas text-left text-xs text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Người dùng</th>
              <th className="px-3 py-2 font-medium">Đăng nhập gần nhất</th>
              <th className="px-3 py-2 text-right font-medium">Lần làm bài</th>
              <th className="px-3 py-2 text-right font-medium">Điểm TB</th>
              <th className="px-3 py-2 text-right font-medium">Tỉ lệ đúng</th>
              <th className="px-3 py-2 text-right font-medium">Slide riêng</th>
            </tr>
          </thead>
          <tbody>
            {list.map((u) => (
              <tr key={u.user_id} onClick={() => setSel(u)} className="cursor-pointer border-b border-line last:border-0 hover:bg-brand-50/40">
                <td className="px-3 py-2">
                  <button onClick={() => setSel(u)} className="flex items-center gap-2.5 text-left cursor-pointer">
                    <Avatar me={asMe(u)} />
                    <span className="min-w-0">
                      <span className="block font-medium">{u.name ?? "—"}{u.is_admin && <span className="ml-1.5 rounded bg-brand-50 px-1 text-xs text-brand-700">Quản trị</span>}</span>
                      <span className="block text-xs text-muted">{u.email ?? "(tài khoản cũ)"}</span>
                    </span>
                  </button>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-muted">{u.last_login_at ? new Date(u.last_login_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" }) : "—"}</td>
                <td className="px-3 py-2 text-right tabular-nums">{u.n_attempts}</td>
                <td className="px-3 py-2 text-right tabular-nums">{u.avg_score == null ? "—" : u.avg_score.toFixed(1)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{pct(u.accuracy)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{u.n_own_docs}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
