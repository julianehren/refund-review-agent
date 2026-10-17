"""Tests for the RAG knowledge base.

A tiny fake embedding (word counts) replaces the real model, so these tests
run in milliseconds and need no download. They test our code (splitting,
indexing, re-indexing, result format) – not the quality of the model.
"""

import hashlib
import re

from chromadb import Documents, EmbeddingFunction, Embeddings

from refund_agent import config
from refund_agent.knowledge import PolicyIndex, load_policy_sections


class WordCountEmbedding(EmbeddingFunction):
    DIM = 256

    def __init__(self):
        pass

    def __call__(self, input: Documents) -> Embeddings:
        vectors = []
        for text in input:
            vector = [0.0] * self.DIM
            for word in re.findall(r"[a-z]+", text.lower()):
                vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.DIM] += 1.0
            vectors.append(vector)
        return vectors

    @staticmethod
    def name() -> str:
        return "word-count-test"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "WordCountEmbedding":
        return WordCountEmbedding()


def test_policy_is_split_into_numbered_sections():
    sections = load_policy_sections()
    ids = [s["section"] for s in sections]
    assert ids == [f"§{n}" for n in range(1, 14)]
    assert all(s["text"].startswith(s["section"]) for s in sections)


def test_search_returns_cited_sections():
    index = PolicyIndex(embedding_function=WordCountEmbedding(), persist_dir=None)
    hits = index.search("chargebacks payment dispute bank", top_k=2)
    assert len(hits) == 2
    assert hits[0]["section"] == "§11"
    assert {"section", "title", "text", "relevance"} <= hits[0].keys()


def test_index_is_rebuilt_when_policy_changes(tmp_path):
    policy = tmp_path / "policy.md"
    policy.write_text(config.POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    index = PolicyIndex(embedding_function=WordCountEmbedding(), persist_dir=tmp_path / "db", policy_path=policy)
    assert index.collection.count() == 13

    policy.write_text(policy.read_text(encoding="utf-8") + "\n## §14 Gift cards\nGift cards are never refunded.\n",
                      encoding="utf-8")
    index = PolicyIndex(embedding_function=WordCountEmbedding(), persist_dir=tmp_path / "db", policy_path=policy)
    assert index.collection.count() == 14
    assert index.search("gift cards refunded", top_k=1)[0]["section"] == "§14"
