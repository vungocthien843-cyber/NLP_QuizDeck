import { useQuery } from "@tanstack/react-query";
import { getJSON } from "@/lib/api";
import { PROCESSING } from "@/lib/format";
import type { DocumentInfo, Quota } from "@/lib/types";

/** Danh sách bài được xem; tự làm mới 4 giây/lần khi còn bài đang xử lý. */
export function useDocuments() {
  return useQuery({
    queryKey: ["documents"],
    queryFn: () => getJSON<DocumentInfo[]>("/documents"),
    refetchInterval: (q) => (q.state.data?.some((d) => PROCESSING.has(d.status)) ? 4000 : false),
  });
}

export function useQuota() {
  return useQuery({ queryKey: ["quota"], queryFn: () => getJSON<Quota>("/documents/quota") });
}
