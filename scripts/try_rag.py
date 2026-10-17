"""Try the policy search from the command line.

Usage:  python scripts/try_rag.py "the pan arrived dented"
"""

import sys

from refund_agent.knowledge import PolicyIndex

query = " ".join(sys.argv[1:]) or "the pan arrived dented"
print(f"Query: {query}\n")
for hit in PolicyIndex().search(query):
    print(f"{hit['relevance']:.3f}  {hit['section']} {hit['title']}")
