import { BookOpen, ChartNoAxesColumn, Settings2 } from "lucide-react";
import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { FullPageSpinner } from "@/components/ui/spinner";
import { UserMenu } from "@/components/UserMenu";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

/** Chặn trang khi chưa đăng nhập: chuyển về /login kèm đường dẫn để quay lại sau khi đăng nhập. */
export function RequireAuth({ admin = false }: { admin?: boolean }) {
  const { me, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <FullPageSpinner />;
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  if (admin && !me.is_admin) return <Navigate to="/" replace />;
  return <Outlet />;
}

export function AppShell() {
  const { me } = useAuth();
  if (!me) return null;
  const links = [
    { to: "/", label: "Học tập", icon: BookOpen, end: true },
    { to: "/ket-qua", label: "Kết quả của tôi", icon: ChartNoAxesColumn, end: false },
    ...(me.is_admin ? [{ to: "/quan-tri", label: "Quản trị", icon: Settings2, end: false }] : []),
  ];
  return (
    <div className="flex h-full flex-col">
      <header className="sticky top-0 z-40 border-b border-line bg-white/90 backdrop-blur">
        <div className="flex h-14 items-center gap-6 px-4 sm:px-6">
          <NavLink to="/" className="flex items-center gap-2.5">
            <img src="/logo-ictu.jpg" alt="ICTU" className="size-8 rounded-full" />
            <span className="hidden font-semibold tracking-tight md:block">Trợ lý học tập</span>
          </NavLink>
          <nav className="flex items-center gap-1" aria-label="Điều hướng chính">
            {links.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                    isActive ? "bg-brand-50 text-brand-700" : "text-muted hover:bg-brand-50 hover:text-ink",
                  )
                }
              >
                <Icon className="size-4" />
                <span className="hidden sm:inline">{label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">
            <UserMenu me={me} />
          </div>
        </div>
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}
