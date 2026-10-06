"""入库接口：单部幂等入库并按需重建 Milvus。"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, HTTPException

from archrag.api.deps import ReadyDep
from archrag.api.schemas import IngestRequest
from archrag.corpus.ingest import ingest_corpus
from archrag.corpus.models import Standard
from archrag.corpus.standard_map import load_standard_map
from archrag.errors import CorpusError
from archrag.retrieval.reindex import reindex

router = APIRouter()
DEV_ALLOWED_FILE = "民用建筑通用规范.md"


@router.post("/api/ingest")
def ingest(payload: IngestRequest, state: ReadyDep) -> dict:
    settings = state.settings
    if not settings.dev_mode and not state.embedder.is_loaded:
        raise HTTPException(
            status_code=503,
            detail={"code": "embedding_not_ready", "message": "嵌入模型未就绪"},
        )
    standard_map = load_standard_map(settings.standard_map_path)
    file_name = payload.file_name or _file_for_standard(standard_map, payload.standard_id)
    if file_name is None or file_name not in standard_map:
        raise HTTPException(status_code=404, detail={"code": "standard_not_found"})
    if settings.dev_mode and file_name != DEV_ALLOWED_FILE:
        raise HTTPException(
            status_code=400,
            detail={"code": "dev_mode_limited", "message": f"DEV_MODE 只入库 {DEV_ALLOWED_FILE}"},
        )
    try:
        outcome = ingest_corpus(
            state.store,
            standard_map,
            corpus_dir=settings.standard_map_path.parent,
            count_tokens=state.token_counter.count,
            files=[file_name],
        )
    except CorpusError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "version_conflict", "message": str(exc)[:200]},
        ) from exc
    stats = outcome.stats[0]
    reindexed: dict[str, int] | None = None
    if not settings.dev_mode:
        report = reindex(state.store, state.milvus, state.embedder)
        reindexed = report.counts
    return {
        "standard_id": stats.standard_id,
        "clauses": stats.clauses,
        "chunks": stats.chunks,
        "created": stats.created,
        "reindexed": reindexed,
        "dev_mode": settings.dev_mode,
    }


def _file_for_standard(
    standard_map: Mapping[str, Standard], standard_id: str | None
) -> str | None:
    if standard_id is None:
        return None
    for file_name, standard in standard_map.items():
        if standard.standard_id == standard_id:
            return file_name
    return None
