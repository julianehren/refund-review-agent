# One image for the REST API and the Streamlit UI (different start commands, see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # keep the embedding model inside the image, not in /tmp
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    # the database lives in a volume, so decisions survive container restarts
    REFUND_DB_PATH=/app/state/shop.db \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# 1. Dependencies first: this layer is cached as long as pyproject.toml does not change
COPY pyproject.toml README.md ./
COPY src/refund_agent/__init__.py src/refund_agent/__init__.py
RUN pip install .

# 2. The project itself
COPY . .
RUN pip install --no-deps -e .

# 3. Download the embedding model and build the policy index at build time,
#    so the first request does not have to wait for it
RUN python -c "from refund_agent.knowledge import PolicyIndex; PolicyIndex()"

# Run as a normal user, not as root
RUN useradd --create-home app && mkdir -p /app/state && chown -R app /app /opt/fastembed
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/entrypoint.sh
# Safety net for Windows checkouts: remove Windows line endings (\r) from the start script
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh

USER app
ENTRYPOINT ["entrypoint.sh"]

EXPOSE 8000 8501
CMD ["uvicorn", "refund_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
