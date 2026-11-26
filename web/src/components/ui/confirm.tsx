import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "./button";

interface Props {
  open: boolean;
  title: string;
  children?: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Hộp thoại xác nhận dùng <dialog> gốc của trình duyệt (khóa focus, Esc để đóng). */
export function ConfirmDialog({ open, title, children, confirmLabel = "Đồng ý", danger, busy, onConfirm, onCancel }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
      className="m-auto w-[min(26rem,calc(100%-2rem))] rounded-xl border border-line p-0 shadow-xl backdrop:bg-ink/30"
    >
      <div className="p-5">
        <h2 className="text-base font-semibold">{title}</h2>
        {children && <div className="mt-2 text-sm text-muted">{children}</div>}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Hủy
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
