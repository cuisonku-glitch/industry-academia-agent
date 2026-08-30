"""Generate local text embeddings for paper chunks with BGE."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Sequence

import torch
from sentence_transformers import SentenceTransformer

try:
    from ..ingestion.chunker import PAPER_METADATA, chunk_document
    from ..ingestion.pdf_parser import parse_papers
except ImportError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from src.ingestion.chunker import PAPER_METADATA, chunk_document
    from src.ingestion.pdf_parser import parse_papers


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
DEFAULT_MODEL_CACHE = PROJECT_ROOT / ".cache" / "huggingface"
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class LocalEmbedder:
    """Load a local Sentence Transformers model and create normalized vectors."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        cache_folder: Path = DEFAULT_MODEL_CACHE,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.cache_folder = cache_folder
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.cache_folder.mkdir(parents=True, exist_ok=True)
        self.model = SentenceTransformer(
            model_name,
            cache_folder=str(cache_folder),
            device=self.device,
        )

    @property
    def dimension(self) -> int:
        """Return the fixed number of values in every embedding vector."""
        return self.model.get_embedding_dimension()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Convert document texts into unit-length embedding vectors."""
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("待 Embedding 的文本不能为空")

        tokenized = self.model.tokenizer(
            list(texts),
            add_special_tokens=True,
            truncation=False,
            padding=False,
        )
        token_lengths = [len(input_ids) for input_ids in tokenized["input_ids"]]
        oversized = [
            index for index, length in enumerate(token_lengths) if length > self.model.max_seq_length
        ]
        if oversized:
            positions = "、".join(str(index + 1) for index in oversized)
            raise ValueError(
                f"第 {positions} 条文本超过模型的 {self.model.max_seq_length} Token 上限，"
                "请减小 Chunk 大小"
            )

        vectors = self.model.encode(
            list(texts),
            batch_size=8,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vectors.tolist()

    def embed_queries(self, queries: Sequence[str]) -> list[list[float]]:
        """Embed retrieval queries with the instruction expected by Chinese BGE."""
        if any(not query.strip() for query in queries):
            raise ValueError("检索问题不能为空")
        instructed_queries = [f"{BGE_QUERY_INSTRUCTION}{query}" for query in queries]
        return self.embed_documents(instructed_queries)


def cosine_similarity(vector_a: Sequence[float], vector_b: Sequence[float]) -> float:
    """Calculate cosine similarity between two equal-length vectors."""
    if len(vector_a) != len(vector_b) or not vector_a:
        raise ValueError("两个向量必须非空且维度相同")

    dot_product = sum(a * b for a, b in zip(vector_a, vector_b))
    norm_a = math.sqrt(sum(value * value for value in vector_a))
    norm_b = math.sqrt(sum(value * value for value in vector_b))
    if norm_a == 0 or norm_b == 0:
        raise ValueError("不能计算零向量的余弦相似度")
    return dot_product / (norm_a * norm_b)


def load_test_chunks(limit: int = 3) -> list[dict[str, Any]]:
    """Select one real chunk from each paper for the first embedding check."""
    if limit <= 0:
        return []

    test_chunks: list[dict[str, Any]] = []
    for parsed_pdf in parse_papers():
        paper_chunks = chunk_document(
            parsed_pdf,
            metadata=PAPER_METADATA.get(parsed_pdf["file_name"]),
        )
        if paper_chunks:
            test_chunks.append(paper_chunks[0])
        if len(test_chunks) == limit:
            break
    return test_chunks


def main() -> None:
    """Generate embeddings for exactly three real chunks and print checks."""
    test_chunks = load_test_chunks(limit=3)
    texts = [chunk["text"] for chunk in test_chunks]

    print(f"Embedding 模型：{DEFAULT_MODEL_NAME}")
    print(f"模型缓存：{DEFAULT_MODEL_CACHE}")
    print("正在加载本地模型（首次运行会自动下载），请稍候……")
    embedder = LocalEmbedder()
    print(f"推理设备：{embedder.device}")
    embeddings = embedder.embed_documents(texts)

    print(f"\n输入文本数量：{len(texts)}")
    print(f"Embedding 数量：{len(embeddings)}")
    print(f"向量维度：{embedder.dimension}")
    print("\n测试 Chunk：")
    for chunk, vector in zip(test_chunks, embeddings):
        metadata = chunk["metadata"]
        print(
            f"- {chunk['chunk_id']}｜作者：{metadata['author']}｜"
            f"页码：{metadata['page_start']}-{metadata['page_end']}｜"
            f"向量前 5 维：{[round(value, 4) for value in vector[:5]]}"
        )

    if len(embeddings) >= 2:
        similarity = cosine_similarity(embeddings[0], embeddings[1])
        print(f"\n前两个测试 Chunk 的余弦相似度：{similarity:.4f}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
