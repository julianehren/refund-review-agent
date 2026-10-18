"""Tests for the online demo's recorded agent runs."""

import json

from refund_agent import config
from refund_agent.demo import is_demo_mode, load_demo_results


def test_recordings_cover_every_labelled_case():
    labels = json.loads(config.LABELS_PATH.read_text(encoding="utf-8"))
    results = load_demo_results()
    assert set(results) == set(labels)
    assert all(result.decision is not None for result in results.values())


def test_demo_mode_switches(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("REFUND_DEMO_MODE", raising=False)
    assert is_demo_mode() is False
    monkeypatch.setenv("REFUND_DEMO_MODE", "1")
    assert is_demo_mode() is True
    monkeypatch.delenv("REFUND_DEMO_MODE")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert is_demo_mode() is True  # no key -> demo mode automatically
