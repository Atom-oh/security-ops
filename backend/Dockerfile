# FSI-Mythos AgentCore container (ARM64 — AgentCore Runtime requires arm64).
FROM --platform=linux/arm64 python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install runtime deps first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code + bundled sample target.
COPY pipeline/ ./pipeline/
COPY agents/ ./agents/
COPY tools/ ./tools/
COPY app.py ./
COPY sample-target/ ./sample-target/

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# AgentCore Runtime invokes the entrypoint; the SDK serves the /invocations contract.
EXPOSE 8080
CMD ["python", "-u", "app.py"]
