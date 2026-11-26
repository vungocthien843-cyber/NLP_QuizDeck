"""Giới hạn số lần gọi theo địa chỉ IP (cửa sổ trượt, trong bộ nhớ). Đủ cho một tiến trình API; chạy nhiều
tiến trình thì thay bằng Redis."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, limit: int, window_s: float):
        self.limit, self.window = limit, window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        ip = request.client.host if request.client else "?"
        now = time.monotonic()
        with self._lock:
            q = self._hits[ip]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(429, "Thao tác quá nhiều lần, vui lòng thử lại sau ít phút",
                                    headers={"Retry-After": str(int(self.window))})
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


auth_limiter = RateLimiter(limit=20, window_s=60)
