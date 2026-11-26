"""Thống kê của mục 9 trong đặc tả, chỉ dùng thư viện chuẩn (container không có scipy).

- bootstrap theo chunk: lấy mẫu lại các chunk (không phải từng câu), vì câu cùng chunk không độc lập.
- hiệu V2 − V1: lấy mẫu lại chung một bộ chunk cho cả hai phiên bản mỗi vòng (so trên cùng nội dung).
- kiểm định nhị thức hai phía so với p0 = 0,25 cho các chỉ số mục tiêu ≈ 25%.
- chi-bình phương với phân bố đều, 3 bậc tự do (A11).
"""
import math
import random


def mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _by_chunk(rows: list[dict], col: str) -> dict:
    out: dict = {}
    for r in rows:
        if r.get(col) is not None:
            out.setdefault(r["chunk_id"], []).append(r[col])
    return out


def _resampled_mean(groups: dict, chunks: list) -> float | None:
    vals = [v for c in chunks for v in groups.get(c, [])]
    return sum(vals) / len(vals) if vals else None


def _ci(samples: list[float]) -> tuple[float | None, float | None]:
    s = sorted(x for x in samples if x is not None)
    if not s:
        return None, None
    return s[int(0.025 * (len(s) - 1))], s[int(0.975 * (len(s) - 1))]


def bootstrap_ci(rows: list[dict], col: str, n: int, seed: int) -> tuple[float | None, float | None]:
    groups = _by_chunk(rows, col)
    chunks = list(groups)
    if not chunks:
        return None, None
    rng = random.Random(seed)
    return _ci([_resampled_mean(groups, rng.choices(chunks, k=len(chunks))) for _ in range(n)])


def bootstrap_diff(rows_a: list[dict], rows_b: list[dict], col: str, n: int, seed: int) -> tuple:
    """Hiệu mean(b) − mean(a) và CI 95%, lấy mẫu lại trên các chunk mà CẢ HAI phiên bản đều có câu."""
    ga, gb = _by_chunk(rows_a, col), _by_chunk(rows_b, col)
    common = sorted(set(ga) & set(gb))
    if not common:
        return None, None, None, 0
    diff = _resampled_mean(gb, common) - _resampled_mean(ga, common)
    rng = random.Random(seed)
    samples = []
    for _ in range(n):
        pick = rng.choices(common, k=len(common))
        samples.append(_resampled_mean(gb, pick) - _resampled_mean(ga, pick))
    lo, hi = _ci(samples)
    return diff, lo, hi, len(common)


def binom_two_sided(k: int, n: int, p0: float = 0.25) -> float | None:
    """p-value chính xác hai phía: cộng xác suất mọi kết quả không khả dĩ hơn kết quả quan sát."""
    if n == 0:
        return None
    pmf = [math.comb(n, i) * p0 ** i * (1 - p0) ** (n - i) for i in range(n + 1)]
    return min(1.0, sum(x for x in pmf if x <= pmf[k] * (1 + 1e-9)))


def chi2_uniform(observed: list[int]) -> tuple[float | None, float | None]:
    n, k = sum(observed), len(observed)
    if n == 0:
        return None, None
    e = n / k
    stat = sum((o - e) ** 2 / e for o in observed)
    if k != 4:
        raise ValueError("chỉ cài sẵn 3 bậc tự do")
    # Hàm sống của chi-bình phương 3 bậc tự do: erfc(√(x/2)) + √(2x/π)·e^(−x/2)
    p = math.erfc(math.sqrt(stat / 2)) + math.sqrt(2 * stat / math.pi) * math.exp(-stat / 2)
    return round(stat, 3), round(min(1.0, p), 4)
