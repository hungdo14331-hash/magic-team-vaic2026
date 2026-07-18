# tools/rag.py
"""
Lightweight domain-specific RAG cho SHB Digital Expert Agents.

Cách hoạt động:
1. Đọc các file Markdown trong data/knowledge.
2. Chia nội dung thành các đoạn theo tiêu đề Markdown.
3. Biểu diễn các đoạn bằng TF-IDF.
4. Tìm các đoạn có độ tương đồng cao nhất với câu hỏi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# Thư mục gốc của project:
# magic-team-vaic2026/tools/rag.py
# => parent.parent là magic-team-vaic2026
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = PROJECT_ROOT / "data" / "knowledge"


# Mỗi Expert được gắn với một miền kiến thức riêng.
EXPERT_KNOWLEDGE_FILES: dict[str, list[str]] = {
    "credit_expert": ["credit_policy.md"],
    "risk_expert": ["credit_policy.md", "legal_compliance.md"],
    "compliance_expert": ["legal_compliance.md"],
    "product_expert": ["products.md"],
    "operations_expert": ["operations.md"],

    # Tên thay thế để tránh lỗi nếu project đang dùng cách đặt tên khác.
    "credit": ["credit_policy.md"],
    "risk": ["credit_policy.md", "legal_compliance.md"],
    "compliance": ["legal_compliance.md"],
    "product": ["products.md"],
    "operations": ["operations.md"],

    # Orchestrator hoặc planner có thể cần tìm trên toàn bộ KB.
    "general": [
        "credit_policy.md",
        "legal_compliance.md",
        "products.md",
        "operations.md",
    ],
}


@dataclass
class KnowledgeChunk:
    """Một đoạn kiến thức được tách ra từ file Markdown."""

    content: str
    source_file: str
    heading: str
    chunk_id: str


class LightweightRAG:
    """RAG đơn giản sử dụng TF-IDF và cosine similarity."""

    def __init__(self, knowledge_dir: Path = KNOWLEDGE_DIR) -> None:
        self.knowledge_dir = knowledge_dir
        self.chunks_by_file: dict[str, list[KnowledgeChunk]] = {}
        self._load_all_files()

    @staticmethod
    def _clean_text(text: str) -> str:
        """Chuẩn hóa khoảng trắng nhưng giữ nguyên nội dung tiếng Việt."""
        text = text.replace("\ufeff", "")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _split_markdown(
        text: str,
        source_file: str,
    ) -> list[KnowledgeChunk]:
        """
        Chia file Markdown theo các heading bắt đầu bằng #, ## hoặc ###.
        Nếu một mục quá dài, tiếp tục chia thành các đoạn nhỏ.
        """
        text = LightweightRAG._clean_text(text)

        heading_pattern = re.compile(
            r"^(#{1,3})\s+(.+?)\s*$",
            flags=re.MULTILINE,
        )

        matches = list(heading_pattern.finditer(text))
        chunks: list[KnowledgeChunk] = []

        if not matches:
            return LightweightRAG._split_long_section(
                content=text,
                source_file=source_file,
                heading="Nội dung chính",
                start_index=1,
            )

        # Nội dung trước heading đầu tiên, nếu có.
        intro = text[:matches[0].start()].strip()
        chunk_counter = 1

        if intro:
            intro_chunks = LightweightRAG._split_long_section(
                content=intro,
                source_file=source_file,
                heading="Giới thiệu",
                start_index=chunk_counter,
            )
            chunks.extend(intro_chunks)
            chunk_counter += len(intro_chunks)

        for index, match in enumerate(matches):
            heading = match.group(2).strip()

            section_start = match.end()
            section_end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(text)
            )

            section_content = text[section_start:section_end].strip()

            if not section_content:
                continue

            section_chunks = LightweightRAG._split_long_section(
                content=section_content,
                source_file=source_file,
                heading=heading,
                start_index=chunk_counter,
            )

            chunks.extend(section_chunks)
            chunk_counter += len(section_chunks)

        return chunks

    @staticmethod
    def _split_long_section(
        content: str,
        source_file: str,
        heading: str,
        start_index: int,
        max_chars: int = 1400,
    ) -> list[KnowledgeChunk]:
        """
        Chia một mục quá dài thành nhiều đoạn dựa trên paragraph.

        max_chars dùng ký tự thay vì token để giữ implementation nhẹ.
        """
        content = LightweightRAG._clean_text(content)

        if len(content) <= max_chars:
            return [
                KnowledgeChunk(
                    content=content,
                    source_file=source_file,
                    heading=heading,
                    chunk_id=f"{source_file}:{start_index}",
                )
            ]

        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", content)
            if paragraph.strip()
        ]

        result: list[KnowledgeChunk] = []
        current_parts: list[str] = []
        current_length = 0
        chunk_index = start_index

        for paragraph in paragraphs:
            paragraph_length = len(paragraph)

            if current_parts and current_length + paragraph_length > max_chars:
                result.append(
                    KnowledgeChunk(
                        content="\n\n".join(current_parts),
                        source_file=source_file,
                        heading=heading,
                        chunk_id=f"{source_file}:{chunk_index}",
                    )
                )
                chunk_index += 1
                current_parts = []
                current_length = 0

            current_parts.append(paragraph)
            current_length += paragraph_length

        if current_parts:
            result.append(
                KnowledgeChunk(
                    content="\n\n".join(current_parts),
                    source_file=source_file,
                    heading=heading,
                    chunk_id=f"{source_file}:{chunk_index}",
                )
            )

        return result

    def _load_all_files(self) -> None:
        """Đọc và chia toàn bộ file Markdown trong knowledge directory."""
        if not self.knowledge_dir.exists():
            raise FileNotFoundError(
                f"Không tìm thấy thư mục kiến thức: {self.knowledge_dir}"
            )

        markdown_files = sorted(self.knowledge_dir.glob("*.md"))

        if not markdown_files:
            raise FileNotFoundError(
                f"Không tìm thấy file .md trong: {self.knowledge_dir}"
            )

        for file_path in markdown_files:
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file_path.read_text(encoding="utf-8-sig")

            chunks = self._split_markdown(
                text=text,
                source_file=file_path.name,
            )

            self.chunks_by_file[file_path.name] = chunks

    def _resolve_files(self, expert_name: str) -> list[str]:
        """Xác định tập file phù hợp với Expert."""
        normalized_name = expert_name.strip().lower()

        if normalized_name in EXPERT_KNOWLEDGE_FILES:
            return EXPERT_KNOWLEDGE_FILES[normalized_name]

        # Hỗ trợ các tên dài như Credit Risk Expert.
        if "compliance" in normalized_name or "legal" in normalized_name:
            return ["legal_compliance.md"]

        if "product" in normalized_name:
            return ["products.md"]

        if "operation" in normalized_name:
            return ["operations.md"]

        if "risk" in normalized_name:
            return ["credit_policy.md", "legal_compliance.md"]

        if "credit" in normalized_name or "loan" in normalized_name:
            return ["credit_policy.md"]

        return EXPERT_KNOWLEDGE_FILES["general"]

    def retrieve(
        self,
        expert_name: str,
        query: str,
        top_k: int = 3,
        min_score: float = 0.02,
    ) -> list[dict[str, Any]]:
        """
        Trả về những đoạn liên quan nhất.

        Args:
            expert_name: Tên Expert cần truy vấn.
            query: Câu hỏi hoặc sub-task.
            top_k: Số đoạn tối đa cần lấy.
            min_score: Ngưỡng cosine similarity tối thiểu.
        """
        if not query or not query.strip():
            return []

        selected_files = self._resolve_files(expert_name)

        candidate_chunks: list[KnowledgeChunk] = []

        for file_name in selected_files:
            candidate_chunks.extend(self.chunks_by_file.get(file_name, []))

        if not candidate_chunks:
            return []

        documents = [
            f"{chunk.heading}\n{chunk.content}"
            for chunk in candidate_chunks
        ]

        # Thêm query vào cuối corpus để vector hóa cùng không gian.
        corpus = documents + [query]

        vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            sublinear_tf=True,
            max_df=1.0,
        )

        matrix = vectorizer.fit_transform(corpus)

        document_vectors = matrix[:-1]
        query_vector = matrix[-1]

        scores = cosine_similarity(
            query_vector,
            document_vectors,
        ).flatten()

        ranked_indices = scores.argsort()[::-1]

        results: list[dict[str, Any]] = []

        for index in ranked_indices:
            score = float(scores[index])

            if score < min_score:
                continue

            chunk = candidate_chunks[index]

            results.append(
                {
                    "content": chunk.content,
                    "source": chunk.source_file,
                    "heading": chunk.heading,
                    "chunk_id": chunk.chunk_id,
                    "score": round(score, 4),
                }
            )

            if len(results) >= max(1, top_k):
                break

        return results

    def format_context(
        self,
        expert_name: str,
        query: str,
        top_k: int = 3,
    ) -> dict[str, Any]:
        """
        Trả context đã định dạng để đưa vào prompt của Expert,
        đồng thời giữ metadata nguồn để hiển thị trên Dashboard.
        """
        results = self.retrieve(
            expert_name=expert_name,
            query=query,
            top_k=top_k,
        )

        if not results:
            return {
                "context": "Không tìm thấy quy định phù hợp trong kho kiến thức.",
                "sources": [],
            }

        context_parts: list[str] = []
        sources: list[dict[str, Any]] = []

        for position, item in enumerate(results, start=1):
            context_parts.append(
                f"[Nguồn {position}: {item['source']} — "
                f"{item['heading']}]\n{item['content']}"
            )

            sources.append(
                {
                    "source": item["source"],
                    "heading": item["heading"],
                    "score": item["score"],
                    "chunk_id": item["chunk_id"],
                }
            )

        return {
            "context": "\n\n".join(context_parts),
            "sources": sources,
        }


# Khởi tạo một lần khi module được import.
_RAG_INSTANCE: LightweightRAG | None = None


def get_rag() -> LightweightRAG:
    """Singleton để không phải đọc lại file ở mỗi lần người dùng hỏi."""
    global _RAG_INSTANCE

    if _RAG_INSTANCE is None:
        _RAG_INSTANCE = LightweightRAG()

    return _RAG_INSTANCE


def retrieve(
    expert_name: str,
    query: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Hàm tiện ích dùng trực tiếp từ các module khác."""
    return get_rag().retrieve(
        expert_name=expert_name,
        query=query,
        top_k=top_k,
    )


def retrieve_context(
    expert_name: str,
    query: str,
    top_k: int = 3,
) -> dict[str, Any]:
    """Lấy context cùng danh sách nguồn trích dẫn."""
    return get_rag().format_context(
        expert_name=expert_name,
        query=query,
        top_k=top_k,
    )