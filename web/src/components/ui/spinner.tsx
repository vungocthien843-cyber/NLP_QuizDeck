import { cn } from "@/lib/utils";

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Đang tải"
      className={cn("inline-block size-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600", className)}
    />
  );
}

export function FullPageSpinner() {
  return (
    <div className="grid h-full place-items-center">
      <Spinner className="size-8" />
    </div>
  );
}
