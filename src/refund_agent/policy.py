"""Reading the store policy (data/store_policy.md) into sections.

Kept separate from knowledge.py on purpose: it needs no vector database, so the
lightweight online demo can show policy sections without installing Chroma.
"""

import re
from pathlib import Path

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
