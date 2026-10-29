"""
RAG (Retrieval-Augmented Generation) engine for the Inventory Assistant.

Provides TF-IDF based document retrieval with no external dependencies.
Supports PDF and CSV document ingestion from the dataset folder.
"""

from __future__ import annotations

import csv
import math
import os
import re
from collections import Counter
from pathlib import Path


def extract_pdf_text(filepath: str) -> str:
    """Extract readable text from a simple PDF file.

    Works with PDFs containing uncompressed text streams using Tj operators.
    For complex PDFs with compressed streams, consider using a library like PyPDF2.
    """
    with open(filepath, "rb") as f:
        raw = f.read()

    text = raw.decode("latin-1", errors="ignore")
    streams = re.findall(r"stream\r?\n(.*?)\r?\nendstream", text, re.DOTALL)

    parts: list[str] = []
    for stream in streams:
        for match in re.findall(r"\(([^)]*)\)\s*Tj", stream):
            unescaped = (
                match.replace("\\(", "(")
                .replace("\\)", ")")
                .replace("\\\\", "\\")
            )
            if unescaped.strip():
                parts.append(unescaped.strip())

    return "\n".join(parts)


def extract_csv_text(filepath: str) -> str:
    """Convert a CSV file into a readable text representation."""
    with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        rows = list(reader)

    if not columns:
        return ""

    name = os.path.basename(filepath)
    lines = [
        f"Document: {name}",
        f"Type: CSV spreadsheet with {len(rows)} rows",
        f"Columns: {', '.join(columns)}",
        "",
    ]

    for row in rows:
        entry = " | ".join(f"{col}: {row.get(col, '').strip()}" for col in columns)
        lines.append(entry)

    return "\n".join(lines)


def chunk_text(text: str, chunk_size: int = 200, overlap: int = 40) -> list[str]:
    """Split text into overlapping chunks by word count."""
    words = text.split()
    if not words:
        return []
    if len(words) <= chunk_size:
        return [text.strip()]

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk.strip())
        if end >= len(words):
            break
        start += chunk_size - overlap

    return chunks


class RAGEngine:
    """TF-IDF based retrieval-augmented generation engine.

    Indexes PDF and CSV documents from a folder and supports
    similarity-based search using TF-IDF vectors and cosine similarity.
    No external dependencies required.
    """

    def __init__(self) -> None:
        self.chunks: list[dict] = []  # {source, type, text, tokens}
        self.idf: dict[str, float] = {}
        self.vectors: list[dict[str, float]] = []
        self.files_info: list[dict] = []
        self.loaded: bool = False

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Lowercase alphanumeric tokenization."""
        return re.findall(r"[a-z0-9]+", text.lower())

    @staticmethod
    def _term_freq(tokens: list[str]) -> dict[str, float]:
        """Compute term frequency for a token list."""
        counts = Counter(tokens)
        total = len(tokens) or 1
        return {w: c / total for w, c in counts.items()}

    def _build_idf(self) -> None:
        """Compute inverse document frequency across all indexed chunks."""
        n = len(self.chunks) or 1
        df: Counter = Counter()
        for chunk in self.chunks:
            for token in set(chunk["tokens"]):
                df[token] += 1
        # Smoothed IDF: log((1 + N) / (1 + df)) + 1
        self.idf = {w: math.log((1 + n) / (1 + c)) + 1 for w, c in df.items()}

    def _tfidf(self, tokens: list[str]) -> dict[str, float]:
        """Compute TF-IDF vector for a token list."""
        tf = self._term_freq(tokens)
        return {w: f * self.idf.get(w, 0.0) for w, f in tf.items()}

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        """Cosine similarity between two sparse vectors."""
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot = sum(a[w] * b[w] for w in common)
        ma = math.sqrt(sum(v * v for v in a.values()))
        mb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (ma * mb) if ma and mb else 0.0

    def ingest(self, folder: str) -> dict:
        """Load and index all PDF and CSV files from *folder*."""
        self.chunks.clear()
        self.files_info.clear()
        path = Path(folder)

        if not path.is_dir():
            self.loaded = False
            return {
                "status": "error",
                "message": f"Folder not found: {folder}",
                "files": [],
                "total_chunks": 0,
                "total_files": 0,
            }

        for fp in sorted(path.iterdir()):
            ext = fp.suffix.lower()
            if ext not in (".pdf", ".csv"):
                continue
            try:
                if ext == ".pdf":
                    text = extract_pdf_text(str(fp))
                else:
                    text = extract_csv_text(str(fp))
                file_chunks = chunk_text(text, chunk_size=150, overlap=30)
                for chunk in file_chunks:
                    tokens = self._tokenize(chunk)
                    if tokens:
                        self.chunks.append(
                            {
                                "source": fp.name,
                                "type": ext.lstrip("."),
                                "text": chunk,
                                "tokens": tokens,
                            }
                        )
                self.files_info.append(
                    {"name": fp.name, "type": ext.lstrip("."), "chunks": len(file_chunks)}
                )
            except Exception as exc:
                self.files_info.append(
                    {"name": fp.name, "type": ext.lstrip("."), "chunks": 0, "error": str(exc)}
                )

        self._build_idf()
        self.vectors = [self._tfidf(c["tokens"]) for c in self.chunks]
        self.loaded = bool(self.chunks)

        return {
            "status": "ok",
            "files": self.files_info,
            "total_chunks": len(self.chunks),
            "total_files": len(self.files_info),
        }

    def search(self, query: str, top_k: int = 5, threshold: float = 0.05) -> list[dict]:
        """Return the *top_k* most relevant chunks for *query*."""
        if not self.chunks:
            return []

        tokens = self._tokenize(query)
        if not tokens:
            return []

        qvec = self._tfidf(tokens)
        scored = [(self._cosine(qvec, v), i) for i, v in enumerate(self.vectors)]
        scored.sort(key=lambda x: -x[0])

        results: list[dict] = []
        for score, idx in scored[:top_k]:
            if score < threshold:
                break
            c = self.chunks[idx]
            results.append(
                {
                    "source": c["source"],
                    "type": c["type"],
                    "content": c["text"],
                    "score": round(score, 4),
                }
            )

        return results

    def get_context(self, query: str, top_k: int = 3) -> str:
        """Return a formatted context string from top results for use in prompts."""
        results = self.search(query, top_k=top_k)
        if not results:
            return ""
        parts = [f"[From {r['source']}]: {r['content']}" for r in results]
        return "\n\n".join(parts)
