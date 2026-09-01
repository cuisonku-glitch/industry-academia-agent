"""Backend-neutral contract for evidence indexes used by retrieval agents."""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class EvidenceIndex(Protocol):
    """Minimal vector-index interface; Chroma is one implementation, not policy."""

    def count(self) -> int: ...

    def get_chunks(
        self, where: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...

    def list_papers(self) -> list[dict[str, Any]]: ...

    def query(
        self,
        query_embedding: Sequence[float],
        top_k: int = 3,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...
