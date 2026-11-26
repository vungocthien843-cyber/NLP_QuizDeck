import type { DocumentInfo } from "./types";

/** Tên bài để hiển thị: bỏ đuôi file, thay gạch dưới bằng khoảng trắng. */
export function docTitle(d: Pick<DocumentInfo, "filename">) {
  return d.filename.replace(/\.(pptx|pdf)$/i, "").replace(/_/g, " ").trim();
}

export const BLOOM_VI: Record<string, string> = { remember: "Nhớ", understand: "Hiểu", apply: "Vận dụng" };

export const PROCESSING = new Set(["uploaded", "parsing", "embedding", "generating"]);

export const STEPS: { key: string; label: string }[] = [
  { key: "parsing", label: "Đọc slide" },
  { key: "embedding", label: "Chia đoạn" },
  { key: "generating", label: "Sinh câu hỏi" },
];

export function slideImageUrl(docId: number, slideNo: number, highlight?: string | null) {
  const base = `/api/documents/${docId}/slides/${slideNo}/image`;
  return highlight ? `${base}?highlight=${encodeURIComponent(highlight.slice(0, 1500))}` : base;
}

export function fmtClock(sec: number) {
  const s = Math.max(0, Math.floor(sec));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
