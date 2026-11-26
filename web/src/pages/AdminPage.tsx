import { BarChart3, FileStack, Users } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { DocumentsAdmin } from "@/features/admin/DocumentsAdmin";
import { Overview } from "@/features/admin/Overview";
import { UsersAdmin } from "@/features/admin/UsersAdmin";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "tong-quan", label: "Tổng quan", icon: BarChart3 },
  { key: "bai-giang", label: "Bài giảng", icon: FileStack },
  { key: "sinh-vien", label: "Sinh viên", icon: Users },
] as const;

export function AdminPage() {
  const [params, setParams] = useSearchParams();
  const tab = TABS.find((t) => t.key === params.get("tab"))?.key ?? "tong-quan";
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight">Quản trị</h1>
        <div role="tablist" aria-label="Mục quản trị" className="mt-4 flex gap-1 border-b border-line">
          {TABS.map((t) => (
            <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setParams({ tab: t.key })} className={cn("flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium cursor-pointer", tab === t.key ? "border-brand-600 text-brand-700" : "border-transparent text-muted hover:text-ink")}>
              <t.icon className="size-4" /> {t.label}
            </button>
          ))}
        </div>
        <div role="tabpanel" className="mt-6">
          {tab === "tong-quan" && <Overview />}
          {tab === "bai-giang" && <DocumentsAdmin />}
          {tab === "sinh-vien" && <UsersAdmin />}
        </div>
      </div>
    </div>
  );
}
