import { Construction } from "lucide-react";

export function Placeholder({ title }: { title: string }) {
  return (
    <div className="grid h-full place-items-center p-10 text-center">
      <div>
        <Construction className="mx-auto size-8 text-muted" />
        <h1 className="mt-3 text-lg font-semibold">{title}</h1>
        <p className="mt-1 text-sm text-muted">Đang xây dựng.</p>
      </div>
    </div>
  );
}

export function NotFound() {
  return (
    <div className="grid h-full place-items-center p-10 text-center">
      <div>
        <p className="text-5xl font-semibold text-brand-600">404</p>
        <p className="mt-2 text-muted">Không tìm thấy trang.</p>
        <a href="/" className="mt-4 inline-block text-sm font-medium text-brand-700 hover:underline">Về trang chính</a>
      </div>
    </div>
  );
}
