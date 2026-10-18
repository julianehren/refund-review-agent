"""RAG (Retrieval-Augmented Generation) over the store policy.

How it works:
1. Split data/store_policy.md into sections (one section = one "## §..." heading).
2. Turn every section into an embedding: a list of numbers that captures its meaning.
3. Store the embeddings in Chroma, a local vector database.
4. When the agent searches, the query is embedded too, and Chroma returns the
   sections whose meaning is closest – even if they use different words
   ("pan arrived dented" finds "§5 Damaged in transit").

The agent then cites the returned section ids in its decision.
"""

import hashlib
import re
import threading
from pathlib import Path

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings

from refund_agent import config


def load_policy_sections(path: Path = config.POLICY_PATH) -> list[dict]:
    """Split the policy markdown into sections like {"section": "§5", "title": ..., "text": ...}."""
    markdown = path.read_text(encoding="utf-8")
    sections = []
    for block in re.split(r"^## ", markdown, flags=re.MULTILINE)[1:]:
        heading, _, body = block.partition("\n")
        match = re.match(r"(§\d+)\s+(.*)", heading.strip())
        if not match:
            continue
        section_id, title = match.groups()
        sections.append({"section": section_id, "title": title, "text": f"{heading.strip()}\n{body.strip()}"})
    return sections


class FastEmbedFunction(EmbeddingFunction):
    """Embeds texts locally with a small open-source model (no API key, runs on CPU).

    The model (~130 MB) is downloaded from Hugging Face on first use and then cached.
    """

    def __init__(self, model_name: str = config.EMBEDDING_MODEL):
        from fastembed import TextEmbedding  # imported here so tests can run without the model

        self.model_name = model_name
        self._model = TextEmbedding(model_name)

    def __call__(self, input: Documents) -> Embeddings:
        return [vector.tolist() for vector in self._model.embed(list(input))]

    @staticmethod
    def name() -> str:
        return "fastembed"

    def get_config(self) -> dict:
        return {"model_name": self.model_name}

    @staticmethod
    def build_from_config(config: dict) -> "FastEmbedFunction":
        return FastEmbedFunction(config["model_name"])


class PolicyIndex:
    """The searchable policy knowledge base."""

    def __init__(self, embedding_function: EmbeddingFunction | None = None,
                 persist_dir: Path | None = config.CHROMA_DIR, policy_path: Path = config.POLICY_PATH):
        self.policy_path = policy_path
        client = chromadb.PersistentClient(path=str(persist_dir)) if persist_dir else chromadb.EphemeralClient()
        self.collection = client.get_or_create_collection(
            name=config.POLICY_COLLECTION,
            embedding_function=embedding_function or FastEmbedFunction(),
            metadata={"hnsw:space": "cosine"},
        )
        self._sync()

    def _sync(self) -> None:
        """(Re)index the policy if it is new or the file has changed since the last run."""
        sections = load_policy_sections(self.policy_path)
        fingerprint = hashlib.sha256(self.policy_path.read_bytes()).hexdigest()
        stored = self.collection.get(limit=1, include=["metadatas"])["metadatas"]
        if stored and stored[0].get("fingerprint") == fingerprint and self.collection.count() == len(sections):
            return  # index is up to date

        existing = self.collection.get()["ids"]
        if existing:
            self.collection.delete(ids=existing)
        self.collection.add(
            ids=[s["section"] for s in sections],
            documents=[s["text"] for s in sections],
            metadatas=[{"section": s["section"], "title": s["title"], "fingerprint": fingerprint} for s in sections],
        )

    def search(self, query: str, top_k: int = config.RAG_TOP_K) -> list[dict]:
        """Return the top_k policy sections that best match the query."""
        result = self.collection.query(query_texts=[query], n_results=top_k)
        return [
            {
                "section": meta["section"],
                "title": meta["title"],
                "text": doc,
                "relevance": round(1 - distance, 3),  # cosine similarity: higher = more relevant
            }
            for doc, meta, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0])
        ]


_shared_index: PolicyIndex | None = None
_shared_index_lock = threading.Lock()


def get_shared_policy_index() -> PolicyIndex:
    """One PolicyIndex per process, created on first use.

    The lock matters: the REST API and the MCP server can receive several
    requests at the same time. Without it, parallel first requests would each
    open the Chroma database at once, which fails (see release v1.1.1).
    """
    global _shared_index
    with _shared_index_lock:
        if _shared_index is None:
            _shared_index = PolicyIndex()
        return _shared_index


SEARCH_POLICIES_SCHEMA = {
    "name": "search_policies",
    "description": "Semantic search in the shop's refund policy. Returns the most relevant policy sections "
                   "(with section ids like '§5'). Search for every aspect of the case you need a rule for, "
                   "e.g. 'transport damage without photo', 'opened hygiene product', 'customer with many refunds'. "
                   "Base your decision only on sections returned by this tool and cite them.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "What rule are you looking for?"}},
        "required": ["query"],
    },
}
