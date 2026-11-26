"""Cache model dùng chung, an toàn khi nhiều luồng gọi cùng lúc.

functools.lru_cache không khoá: 5 câu sinh song song (asyncio.to_thread) cùng gọi get_generator() lúc cache
trống sẽ nạp model 5 lần cùng lúc. Với transformers 5.x, nạp đồng thời làm hỏng việc gắn trọng số dùng chung
(lm_head/embed_tokens báo MISSING, bị khởi tạo ngẫu nhiên) và ViT5 sinh ra rác (ablation 20261108-023413).
"""
import threading
from functools import lru_cache, wraps

_LOAD_LOCK = threading.RLock()     # RLock: hàm nạp model này có thể gọi hàm nạp model khác


def thread_safe_cache(fn):
    cached = lru_cache(fn)

    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _LOAD_LOCK:
            return cached(*args, **kwargs)
    wrapper.cache_clear = cached.cache_clear
    return wrapper
