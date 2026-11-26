import { cn } from "@/lib/utils";

interface Props<T extends string> {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  label: string;
  className?: string;
}

/** Nhóm nút chọn một (radiogroup), điều khiển được bằng phím mũi tên. */
export function Segmented<T extends string>({ value, onChange, options, label, className }: Props<T>) {
  const idx = options.findIndex((o) => o.value === value);
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn("inline-flex w-full rounded-lg border border-line bg-white p-0.5", className)}
      onKeyDown={(e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        e.preventDefault();
        const next = options[(idx + (e.key === "ArrowRight" ? 1 : options.length - 1)) % options.length];
        onChange(next.value);
      }}
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1}
          onClick={() => onChange(o.value)}
          className={cn(
            "flex-1 rounded-md px-2 py-1.5 text-sm font-medium transition-colors cursor-pointer",
            o.value === value ? "bg-brand-600 text-white shadow-sm" : "text-muted hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
