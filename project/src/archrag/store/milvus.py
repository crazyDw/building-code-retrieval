"""Milvus 派生索引：只存向量与定位标量，不存原文正文。

dense 用 FLAT + COSINE；sparse 用 SPARSE_INVERTED_INDEX + IP（D12）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from archrag.errors import StoreError

DENSE_FIELD = "dense"
SPARSE_FIELD = "sparse"
DENSE_DIM = 1024
SCALAR_FIELDS = (
    "standard_id",
    "level",
    "chunk_type",
    "clause_id",
    "section_id",
    "clause_no",
    "kuan_no",
    "table_id",
    "row_no",
)
OUTPUT_FIELDS = ("chunk_id", *SCALAR_FIELDS)


@dataclass(frozen=True, slots=True)
class ChunkVector:
    """一个块的向量与定位标量；原文不进入 Milvus。"""

    chunk_id: str
    standard_id: str
    level: str
    chunk_type: str
    clause_id: str | None
    section_id: str | None
    clause_no: str | None
    kuan_no: int | None
    table_id: str | None
    row_no: int | None
    dense: tuple[float, ...]
    sparse: dict[int, float]

    def to_row(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "standard_id": self.standard_id,
            "level": self.level,
            "chunk_type": self.chunk_type,
            "clause_id": self.clause_id or "",
            "section_id": self.section_id or "",
            "clause_no": self.clause_no or "",
            "kuan_no": int(self.kuan_no or 0),
            "table_id": self.table_id or "",
            "row_no": int(self.row_no or 0),
            DENSE_FIELD: list(self.dense),
            SPARSE_FIELD: {int(key): float(value) for key, value in self.sparse.items()},
        }


@dataclass(frozen=True, slots=True)
class MilvusHit:
    """检索命中：chunk_id + 分数 + 定位标量。"""

    chunk_id: str
    score: float
    fields: dict[str, Any]


class MilvusStore:
    """collection 管理、写入与两路检索；客户端懒加载。"""

    def __init__(self, uri: str, collection: str, *, dim: int = DENSE_DIM) -> None:
        self.uri = uri
        self.collection = collection
        self.dim = dim
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from pymilvus import MilvusClient

            self._client = MilvusClient(uri=self.uri)
        return self._client

    def is_available(self) -> bool:
        try:
            self._get_client().list_collections()
            return True
        except Exception:
            return False

    def drop(self) -> None:
        client = self._get_client()
        if client.has_collection(self.collection):
            client.drop_collection(self.collection)

    def ensure_collection(self, *, drop_existing: bool = False) -> None:
        client = self._get_client()
        if client.has_collection(self.collection):
            if drop_existing:
                client.drop_collection(self.collection)
            else:
                client.load_collection(self.collection)
                return
        from pymilvus import DataType, MilvusClient

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            field_name="chunk_id", datatype=DataType.VARCHAR, is_primary=True, max_length=128
        )
        schema.add_field(field_name="standard_id", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="level", datatype=DataType.VARCHAR, max_length=16)
        schema.add_field(field_name="chunk_type", datatype=DataType.VARCHAR, max_length=16)
        schema.add_field(field_name="clause_id", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="section_id", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="clause_no", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="kuan_no", datatype=DataType.INT64)
        schema.add_field(field_name="table_id", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="row_no", datatype=DataType.INT64)
        schema.add_field(field_name=DENSE_FIELD, datatype=DataType.FLOAT_VECTOR, dim=self.dim)
        schema.add_field(field_name=SPARSE_FIELD, datatype=DataType.SPARSE_FLOAT_VECTOR)

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name=DENSE_FIELD, index_type="FLAT", metric_type="COSINE"
        )
        index_params.add_index(
            field_name=SPARSE_FIELD,
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="IP",
        )
        client.create_collection(
            collection_name=self.collection,
            schema=schema,
            index_params=index_params,
        )
        client.load_collection(self.collection)

    def insert_chunks(self, vectors: Sequence[ChunkVector]) -> int:
        if not vectors:
            return 0
        client = self._get_client()
        rows = [vector.to_row() for vector in vectors]
        client.insert(collection_name=self.collection, data=rows)
        return len(rows)

    def flush(self) -> None:
        """显式落盘；批量写入结束后调用一次即可。"""
        self._get_client().flush(self.collection)

    def delete_standard(self, standard_id: str) -> None:
        client = self._get_client()
        client.delete(collection_name=self.collection, filter=_standard_filter(standard_id))
        client.flush(self.collection)

    def count(self, standard_id: str | None = None) -> int:
        client = self._get_client()
        expression = _standard_filter(standard_id) if standard_id else 'chunk_id != ""'
        rows = client.query(
            collection_name=self.collection,
            filter=expression,
            output_fields=["count(*)"],
        )
        if not rows:
            return 0
        return int(rows[0]["count(*)"])

    def search_dense(
        self,
        vector: Sequence[float],
        *,
        top_k: int = 30,
        standard_id: str | Sequence[str] | None = None,
    ) -> list[MilvusHit]:
        raw = self._get_client().search(
            collection_name=self.collection,
            data=[list(vector)],
            anns_field=DENSE_FIELD,
            search_params={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            filter=_standard_filter(standard_id),
            output_fields=list(OUTPUT_FIELDS),
        )
        return _parse_hits(raw)

    def search_sparse(
        self,
        sparse: dict[int, float],
        *,
        top_k: int = 30,
        standard_id: str | Sequence[str] | None = None,
    ) -> list[MilvusHit]:
        if not sparse:
            raise StoreError("sparse 查询向量为空")
        raw = self._get_client().search(
            collection_name=self.collection,
            data=[{int(key): float(value) for key, value in sparse.items()}],
            anns_field=SPARSE_FIELD,
            search_params={"metric_type": "IP", "params": {}},
            limit=top_k,
            filter=_standard_filter(standard_id),
            output_fields=list(OUTPUT_FIELDS),
        )
        return _parse_hits(raw)


def _standard_filter(standard_id: str | Sequence[str] | None) -> str:
    if standard_id is None:
        return ""
    if not isinstance(standard_id, str):
        items = list(standard_id)
        if not items:
            return ""
        joined = ", ".join(f'"{item}"' for item in items)
        return f"standard_id in [{joined}]"
    return f'standard_id == "{standard_id}"'


def _parse_hits(raw: Any) -> list[MilvusHit]:
    if not raw:
        return []
    hits: list[MilvusHit] = []
    for item in raw[0]:
        if isinstance(item, dict):
            entity = dict(item.get("entity") or {})
            chunk_id = entity.get("chunk_id", item.get("id", ""))
            score = item.get("distance", item.get("score", 0.0)) or 0.0
        else:  # pymilvus ORM Hit
            entity = {field: item.entity.get(field) for field in OUTPUT_FIELDS}
            chunk_id = entity.get("chunk_id", "")
            score = item.score
        hits.append(
            MilvusHit(chunk_id=str(chunk_id), score=float(score), fields=entity)
        )
    return hits
