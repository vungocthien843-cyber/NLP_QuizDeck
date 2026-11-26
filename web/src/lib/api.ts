/**
 * Gọi backend qua cùng địa chỉ (/api → FastAPI). Cookie phiên là HttpOnly nên JavaScript không đọc được;
 * trình duyệt tự gửi kèm. Yêu cầu thay đổi dữ liệu phải kèm X-CSRF-Token lấy từ /auth/me.
 */
export const API = "/api";

let csrfToken: string | null = null;
export function setCsrfToken(t: string | null) {
  csrfToken = t;
}


export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Listener = () => void;
const unauthorizedListeners = new Set<Listener>();
/** Đăng ký hàm chạy khi phiên hết hạn (API trả 401) để đưa người dùng về trang đăng nhập. */
export function onUnauthorized(fn: Listener) {
  unauthorizedListeners.add(fn);
  return () => {
    unauthorizedListeners.delete(fn);
  };
}

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map((d: { msg?: string }) => d.msg).join("; ");
  } catch {
    /* không phải JSON */
  }
  return res.statusText || `Lỗi ${res.status}`;
}

export async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (method !== "GET" && method !== "HEAD" && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  let res: Response;
  try {
    res = await fetch(API + path, { ...init, method, headers, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "Không kết nối được máy chủ. Kiểm tra mạng hoặc thử lại sau.");
  }
  if (res.status === 401 && path !== "/auth/me") unauthorizedListeners.forEach((fn) => fn());
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  return res;
}

export async function getJSON<T>(path: string): Promise<T> {
  return (await request(path)).json();
}

export async function sendJSON<T>(path: string, body: unknown, method = "POST"): Promise<T> {
  const res = await request(path, { method, body: JSON.stringify(body) });
  return res.status === 204 ? (undefined as T) : res.json();
}

/** Chuyển cả trang sang luồng đăng nhập Google (không dùng fetch vì phải đi qua trang của Google). */
export function startGoogleLogin(next: string = window.location.pathname + window.location.search) {
  const safe = next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login") ? next : "/";
  window.location.assign(`${API}/auth/login?next=${encodeURIComponent(safe)}`);
}

/** Tải file lên kèm tiến độ (fetch chưa báo tiến độ upload nên dùng XMLHttpRequest). */
export function uploadFile<T>(path: string, form: FormData, onProgress?: (pct: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", API + path);
    xhr.withCredentials = true;
    if (csrfToken) xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(Math.round((e.loaded / e.total) * 100));
    xhr.onerror = () => reject(new ApiError(0, "Không kết nối được máy chủ."));
    xhr.onload = () => {
      let body: { detail?: unknown } | null = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* bỏ qua */
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(body as T);
      if (xhr.status === 401) unauthorizedListeners.forEach((fn) => fn());
      reject(new ApiError(xhr.status, typeof body?.detail === "string" ? body.detail : `Lỗi ${xhr.status}`));
    };
    xhr.send(form);
  });
}
