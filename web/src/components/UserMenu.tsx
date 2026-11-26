import { LogOut, MonitorX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import type { Me } from "@/lib/types";
import { cn } from "@/lib/utils";

function initials(me: Me) {
  const src = (me.name || me.email || "?").trim();
  const parts = src.split(/\s+/);
  return (parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : src.slice(0, 2)).toUpperCase();
}

export function Avatar({ me, className }: { me: Me; className?: string }) {
  const [broken, setBroken] = useState(false);
  if (me.avatar_url && !broken) {
    return (
      <img
        src={me.avatar_url}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
        className={cn("size-8 rounded-full object-cover", className)}
      />
    );
  }
  return (
    <span className={cn("grid size-8 place-items-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800", className)}>
      {initials(me)}
    </span>
  );
}

export function UserMenu({ me }: { me: Me }) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const doLogout = async (everywhere: boolean) => {
    setOpen(false);
    await logout(everywhere);
    navigate("/login", { replace: true });
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full p-0.5 pr-2 hover:bg-brand-50 cursor-pointer"
      >
        <Avatar me={me} />
        <span className="hidden max-w-40 truncate text-sm font-medium sm:block">{me.name ?? me.email}</span>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-50 mt-2 w-72 overflow-hidden rounded-xl border border-line bg-white shadow-lg">
          <div className="flex items-center gap-3 border-b border-line p-4">
            <Avatar me={me} className="size-10" />
            <div className="min-w-0">
              <p className="truncate font-medium">{me.name}</p>
              <p className="truncate text-sm text-muted">{me.email}</p>
              {me.is_admin && (
                <span className="mt-1 inline-block rounded bg-brand-50 px-1.5 py-0.5 text-xs font-medium text-brand-700">
                  Quản trị viên
                </span>
              )}
            </div>
          </div>
          <div className="p-1">
            <button role="menuitem" onClick={() => doLogout(false)} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm hover:bg-brand-50 cursor-pointer">
              <LogOut className="size-4 text-muted" /> Đăng xuất
            </button>
            <button role="menuitem" onClick={() => doLogout(true)} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm hover:bg-brand-50 cursor-pointer">
              <MonitorX className="size-4 text-muted" /> Đăng xuất trên mọi thiết bị
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
