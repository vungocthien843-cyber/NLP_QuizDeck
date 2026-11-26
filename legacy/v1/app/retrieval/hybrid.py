"""Hàm retrieve dùng chung: dense + sparse → RRF → (tuỳ chọn) rerank (mục 6)."""
from dataclasses import dataclass

from pgvector.sqlalchemy import SPARSEVEC, Vector
from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from app.config import get_config
from app.models import EMBED_DIM, SPARSE_DIM, Chunk
from app.retrieval.embedder import get_embedder
from app.schemas import RetrievedChunk, Scope


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    best_dense: float | None      # cosine cao nhất của nhánh dense, dùng cho luật từ chối sớm


def scope_filter_sql(scope: Scope, exclude_ids: set[int] | None = None) -> tuple[str, dict]:
    """Dựng mệnh đề WHERE (alias bảng chunks là c) và tham số."""
    clauses, params = ["c.is_active"], {}
    if scope.document_ids:
        clauses.append("c.document_id = ANY(:docs)")
        params["docs"] = scope.document_ids
    if scope.session_nos:
        clauses.append("c.session_no = ANY(:sessions)")
        params["sessions"] = scope.session_nos
    if scope.slide_from:
        clauses.append("c.slide_end >= :slide_from")
        params["slide_from"] = scope.slide_from
    if scope.slide_to:
        clauses.append("c.slide_no <= :slide_to")
        params["slide_to"] = scope.slide_to
    if scope.chapter_nos:
        clauses.append("c.chapter_no = ANY(:chapters)")
        params["chapters"] = scope.chapter_nos
    if exclude_ids:
        clauses.append("NOT (c.id = ANY(:exclude))")
        params["exclude"] = list(exclude_ids)
    return " AND ".join(clauses), params


def dense_search(db: Session, query_vec, scope: Scope, top_n: int,
                 exclude_ids: set[int] | None = None) -> list[tuple[int, float]]:
    """Quét tuần tự theo cosine (không HNSW nên lọc luôn đủ kết quả). Trả [(chunk_id, cosine)]."""
    where, params = scope_filter_sql(scope, exclude_ids)
    stmt = text(
        f"SELECT c.id, 1 - (c.embedding <=> :q) AS score FROM chunks c "
        f"WHERE {where} AND c.embedding IS NOT NULL ORDER BY c.embedding <=> :q LIMIT :n"
    ).bindparams(bindparam("q", type_=Vector(EMBED_DIM)))
    return [(r.id, float(r.score)) for r in db.execute(stmt, {**params, "q": query_vec, "n": top_n})]


def sparse_search(db: Session, query_sparse, scope: Scope, top_n: int,
                  exclude_ids: set[int] | None = None) -> list[tuple[int, float]]:
    """Điểm lexical bge-m3 là tích vô hướng; <#> trả về ÂM inner product."""
    where, params = scope_filter_sql(scope, exclude_ids)
    stmt = text(
        f"SELECT c.id, -(c.sparse <#> :qs) AS score FROM chunks c "
        f"WHERE {where} AND c.sparse IS NOT NULL ORDER BY c.sparse <#> :qs LIMIT :n"
    ).bindparams(bindparam("qs", type_=SPARSEVEC(SPARSE_DIM)))
    rows = db.execute(stmt, {**params, "qs": query_sparse, "n": top_n})
    return [(r.id, float(r.score)) for r in rows if r.score > 0]


def tsvector_search(db: Session, query: str, scope: Scope, top_n: int,
                    exclude_ids: set[int] | None = None) -> list[tuple[int, float]]:
    """Nối các từ của query bằng OR (plainto_tsquery nối AND nên câu dài gần như không khớp gì)."""
    where, params = scope_filter_sql(scope, exclude_ids)
    stmt = text(
        f"WITH q AS (SELECT to_tsquery('simple', array_to_string("
        f"  tsvector_to_array(to_tsvector('simple', :query)), ' | ')) AS query) "
        f"SELECT c.id, ts_rank(c.tsv, q.query) AS score FROM chunks c, q "
        f"WHERE {where} AND c.tsv @@ q.query ORDER BY score DESC LIMIT :n"
    )
    return [(r.id, float(r.score)) for r in db.execute(stmt, {**params, "query": query, "n": top_n})]


def rrf(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def retrieve_detailed(
    db: Session,
    query: str,
    scope: Scope | None = None,
    *,
    k: int | None = None,
    rerank: bool | None = None,
    exclude_ids: set[int] | None = None,
    mode: str = "hybrid",
) -> RetrievalResult:
    """mode: hybrid | dense | sparse (dùng cho thí nghiệm đánh giá)."""
    cfg = get_config().retrieval
    scope = scope or Scope()
    k = k or cfg.k
    rerank = cfg.rerank if rerank is None else rerank

    emb = get_embedder().encode_one(query)
    dense = dense_search(db, emb.dense, scope, cfg.top_n, exclude_ids)
    if cfg.sparse_backend == "bge":
        sparse = sparse_search(db, emb.sparse, scope, cfg.top_n, exclude_ids)
    else:
        sparse = tsvector_search(db, query, scope, cfg.top_n, exclude_ids)

    rankings = {"dense": [[i for i, _ in dense]], "sparse": [[i for i, _ in sparse]],
                "hybrid": [[i for i, _ in dense], [i for i, _ in sparse]]}[mode]
    ranked = rrf(rankings, cfg.rrf_k)
    dense_scores = dict(dense)
    best_dense = dense[0][1] if dense else None

    ids = [i for i, _ in ranked]
    chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_(ids)))} if ids else {}
    if rerank and ids:
        from app.retrieval.reranker import get_reranker

        ranked = get_reranker().rerank(query, [(i, chunks[i].embed_text) for i in ids])

    results = [
        RetrievedChunk(
            chunk_id=c.id, session_no=c.session_no, slide_no=c.slide_no, slide_end=c.slide_end, title=c.title,
            raw_text=c.raw_text, image_path=c.image_path, score=score, dense_score=dense_scores.get(c.id),
        )
        for chunk_id, score in ranked[:k]
        if (c := chunks.get(chunk_id))
    ]
    return RetrievalResult(chunks=results, best_dense=best_dense)


def retrieve(db: Session, query: str, scope: Scope | None = None, **kwargs) -> list[RetrievedChunk]:
    return retrieve_detailed(db, query, scope, **kwargs).chunks
