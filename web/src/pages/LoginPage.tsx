import { AlertCircle, BookOpenCheck, MessagesSquare, Microscope } from "lucide-react";
import { Navigate, useSearchParams } from "react-router-dom";
import { GoogleIcon } from "@/components/GoogleIcon";
import { Button } from "@/components/ui/button";
import { FullPageSpinner } from "@/components/ui/spinner";
import { useAuth } from "@/lib/auth";

const ERRORS: Record<string, string> = {
  domain: "Chỉ tài khoản Google của trường (@ictu.edu.vn) được đăng nhập. Hãy chọn đúng tài khoản sinh viên.",
  unverified: "Email của tài khoản Google này chưa được xác minh.",
  cancelled: "Bạn đã hủy đăng nhập.",
  expired: "Phiên đăng nhập đã quá hạn. Vui lòng bấm đăng nhập lại.",
  state: "Yêu cầu đăng nhập không hợp lệ. Vui lòng thử lại.",
  token: "Không xác minh được tài khoản Google. Vui lòng thử lại.",
  google: "Không kết nối được Google. Vui lòng thử lại sau ít phút.",
  conflict: "Email này đã gắn với một tài khoản Google khác. Liên hệ quản trị viên.",
};

const FEATURES = [
  { icon: BookOpenCheck, title: "Đề trắc nghiệm từ slide", text: "Câu hỏi sinh tự động, bám sát nội dung bài giảng." },
  { icon: Microscope, title: "Chẩn đoán chỗ hiểu sai", text: "Mỗi phương án sai ứng với một kiểu hiểu lầm cụ thể." },
  { icon: MessagesSquare, title: "Trợ lý hỏi đáp", text: "Giải thích có trích dẫn đúng slide làm căn cứ." },
];

export function LoginPage() {
  const { me, loading, login } = useAuth();
  const [params] = useSearchParams();
  const next = params.get("next") ?? "/";
  const error = params.get("error");

  if (loading) return <FullPageSpinner />;
  if (me) return <Navigate to={next} replace />;

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-brand-800 text-white lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-32 -top-32 size-[28rem] rounded-full bg-brand-600/40 blur-3xl"
        />
        <div className="relative flex items-center gap-3">
          <img src="/logo-ictu.jpg" alt="" className="size-11 rounded-full bg-white p-0.5" />
          <div className="leading-tight">
            <p className="text-sm text-brand-100">Trường Đại học Công nghệ Thông tin và Truyền thông</p>
            <p className="font-semibold">Trợ lý học tập</p>
          </div>
        </div>

        <div className="relative max-w-lg">
          <h1 className="text-4xl font-semibold leading-tight tracking-tight text-balance">
            Ôn tập từ chính slide bài giảng của bạn
          </h1>
          <ul className="mt-10 space-y-6">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-white/10">
                  <Icon className="size-5" />
                </span>
                <span>
                  <span className="block font-medium">{title}</span>
                  <span className="block text-sm text-brand-100">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-xs text-brand-200">
          Hệ thống sinh câu hỏi trắc nghiệm từ slide bài giảng ứng dụng RAG · Nhóm 03
        </p>
      </aside>

      <main className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <img src="/logo-ictu.jpg" alt="" className="size-10 rounded-full" />
            <p className="font-semibold">ICTU · Trợ lý học tập</p>
          </div>

          <h2 className="text-2xl font-semibold tracking-tight">Đăng nhập</h2>
          <p className="mt-2 text-sm text-muted">Dùng tài khoản Google sinh viên do trường cấp.</p>

          {error && (
            <div role="alert" className="mt-6 flex gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
              <span>{ERRORS[error] ?? "Đăng nhập không thành công. Vui lòng thử lại."}</span>
            </div>
          )}

          <Button variant="secondary" size="lg" className="mt-8 w-full" onClick={() => login(next)}>
            <GoogleIcon className="size-5" />
            Đăng nhập bằng Google
          </Button>

          <p className="mt-4 text-center text-xs text-muted">
            Chỉ chấp nhận email <span className="font-medium text-ink">@ictu.edu.vn</span>
          </p>
        </div>
      </main>
    </div>
  );
}
