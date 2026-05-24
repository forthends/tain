"""
Vector Store — 纯Python TF-IDF 向量存储

A zero-dependency semantic search engine for the agent's knowledge base.
Uses TF-IDF (Term Frequency - Inverse Document Frequency) with cosine similarity.

Design:
  - Indexes markdown files in knowledge/ directory
  - Splits documents by ## section headings
  - Tokenizes: lowercase → filter alpha → remove stopwords → stem (simple)
  - TF variant: ln(1 + ln(1 + tf))  (sublinear scaling)
  - IDF: ln((N - df + 0.5) / (df + 0.5) + 1)  (BM25 variant, handles df=0)
  - Cosine similarity for ranking

Usage:
  store = TfidfVectorStore("knowledge/")
  store.index()
  results = store.search("how does self improvement work?", top_k=3)

No numpy, no sklearn, no external dependencies. Pure Python.
"""

import math
import re
from collections import Counter
from pathlib import Path
from typing import Optional


# ─── Tokenizer ────────────────────────────────────────────────────────

# Common English stopwords
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "shall", "not",
    "no", "nor", "so", "if", "then", "else", "when", "where", "which",
    "who", "whom", "this", "that", "these", "those", "it", "its",
    "we", "you", "he", "she", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "our", "their", "all", "each", "every", "both",
    "few", "more", "most", "other", "some", "such", "only", "own",
    "same", "than", "too", "very", "just", "about", "above", "after",
    "again", "against", "between", "into", "through", "during", "before",
    "here", "there", "while", "also", "up", "down", "out", "off",
    "over", "under", "once", "here", "there", "how", "what", "why",
})


def tokenize(text: str) -> list[str]:
    """Tokenize text into meaningful terms."""
    # Lowercase and extract alphabetic sequences (min length 2)
    tokens = re.findall(r"[a-z]{2,}", text.lower())
    # Remove stopwords
    return [t for t in tokens if t not in _STOPWORDS]


# ─── Vector Store ─────────────────────────────────────────────────────

class TfidfVectorStore:
    """Pure-Python TF-IDF vector store for semantic search."""

    def __init__(self, knowledge_dir: str = "knowledge"):
        self.knowledge_dir = Path(knowledge_dir)
        self.chunks: list[dict] = []       # Each: {id, file, section, text, tokens}
        self.vocab: dict[str, int] = {}     # term → index
        self.idf: dict[str, float] = {}     # term → idf score
        self.vectors: list[dict[int, float]] = []  # TF-IDF sparse vectors
        self.indexed_files: set[str] = set()

    # ── Parsing ──────────────────────────────────────────────────

    def _parse_markdown(self, filepath: Path) -> list[dict]:
        """Parse a markdown file into chunks by sections."""
        text = filepath.read_text(encoding="utf-8")
        chunks = []

        # Split by ## headings (but keep file-level content as first chunk)
        sections = re.split(r"\n(?=#{1,3}\s)", text)

        current_section = "(top)"
        for i, section in enumerate(sections):
            # Extract heading
            heading_match = re.match(r"#{1,3}\s+(.+)", section)
            if heading_match:
                current_section = heading_match.group(1).strip()

            # Skip empty sections
            content = section.strip()
            if not content:
                continue

            # Skip pure heading lines (no body)
            body = re.sub(r"^#{1,3}\s+.+\n?", "", content).strip()
            if not body:
                continue

            chunks.append({
                "file": str(filepath.relative_to(self.knowledge_dir.parent)),
                "section": current_section,
                "text": content[:2000],  # Truncate long sections
                "tokens": tokenize(content),
            })

        return chunks

    # ── Indexing ─────────────────────────────────────────────────

    def index(self):
        """Index all markdown files in knowledge_dir."""
        self.chunks = []
        self.indexed_files = set()

        if not self.knowledge_dir.exists():
            return

        for filepath in sorted(self.knowledge_dir.glob("*.md")):
            chunks = self._parse_markdown(filepath)
            for i, chunk in enumerate(chunks):
                chunk["id"] = f"{filepath.stem}:{i}"
            self.chunks.extend(chunks)
            self.indexed_files.add(str(filepath.relative_to(self.knowledge_dir.parent)))

        # Build vocabulary
        df = Counter()  # document frequency
        for chunk in self.chunks:
            unique_terms = set(chunk["tokens"])
            for term in unique_terms:
                df[term] += 1

        # Sort by frequency and assign indices
        sorted_terms = sorted(df.keys(), key=lambda t: df[t], reverse=True)
        self.vocab = {term: idx for idx, term in enumerate(sorted_terms)}

        # Compute IDF
        N = len(self.chunks)
        self.idf = {}
        for term, doc_freq in df.items():
            # Smooth IDF (prevent division by zero)
            self.idf[term] = math.log((N - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)

        # Compute TF-IDF vectors
        self.vectors = []
        for chunk in self.chunks:
            vec = {}
            term_counts = Counter(chunk["tokens"])
            for term, count in term_counts.items():
                if term in self.vocab:
                    idx = self.vocab[term]
                    # Sublinear TF scaling: ln(1 + ln(1 + tf))
                    tf = math.log(1 + math.log(1 + count))
                    vec[idx] = tf * self.idf.get(term, 0)
            self.vectors.append(vec)

    # ── Search ───────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search by cosine similarity.

        Returns list of {id, file, section, score, snippet}.
        """
        if not self.vectors:
            return [{"error": "Index is empty. Call index() first."}]

        # Tokenize and compute query vector
        query_tokens = tokenize(query)
        query_counts = Counter(query_tokens)

        query_vec = {}
        for term, count in query_counts.items():
            if term in self.vocab and term in self.idf:
                idx = self.vocab[term]
                tf = math.log(1 + math.log(1 + count))
                query_vec[idx] = tf * self.idf[term]

        if not query_vec:
            return [{"error": "No known terms in query."}]

        # Compute cosine similarity
        scores = []
        query_norm = math.sqrt(sum(v * v for v in query_vec.values()))

        for i, doc_vec in enumerate(self.vectors):
            if not doc_vec:
                continue
            # Dot product
            dot = sum(query_vec.get(idx, 0) * val for idx, val in doc_vec.items())
            # Document norm
            doc_norm = math.sqrt(sum(v * v for v in doc_vec.values()))
            if doc_norm == 0:
                continue
            similarity = dot / (query_norm * doc_norm)
            if similarity > 0:
                scores.append((similarity, i))

        # Sort by score descending
        scores.sort(key=lambda x: x[0], reverse=True)
        top = scores[:top_k]

        results = []
        for score, idx in top:
            chunk = self.chunks[idx]
            # Generate snippet (first 200 chars of text)
            snippet = chunk["text"][:200].replace("\n", " ")
            results.append({
                "id": chunk["id"],
                "file": chunk["file"],
                "section": chunk["section"],
                "score": round(score, 4),
                "snippet": snippet + ("..." if len(chunk["text"]) > 200 else ""),
            })

        return results

    # ── Stats ────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return index statistics."""
        return {
            "chunks": len(self.chunks),
            "vocabulary_size": len(self.vocab),
            "indexed_files": sorted(self.indexed_files),
            "avg_chunk_length": (
                sum(len(c["tokens"]) for c in self.chunks) / max(len(self.chunks), 1)
            ),
        }


# ─── Singleton (for tool access) ──────────────────────────────────────

_store: Optional[TfidfVectorStore] = None


def get_store(knowledge_dir: str = "knowledge") -> TfidfVectorStore:
    """Get or create the singleton vector store."""
    global _store
    if _store is None or str(_store.knowledge_dir) != str(Path(knowledge_dir)):
        _store = TfidfVectorStore(knowledge_dir)
    return _store


def search_knowledge(query: str, top_k: int = 5, reindex: bool = False) -> list[dict]:
    """Search the knowledge base semantically.

    Args:
        query: Natural language query.
        top_k: Number of results (default 5).
        reindex: Force reindexing (default False).

    Returns:
        List of {file, section, score, snippet}.
    """
    store = get_store()

    if reindex or not store.vectors:
        store.index()

    return store.search(query, top_k)


def index_stats() -> dict:
    """Get vector store statistics."""
    store = get_store()
    if not store.vectors:
        store.index()
    return store.stats()
