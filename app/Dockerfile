# syntax=docker/dockerfile:1
FROM python:3.14.5-slim-bookworm AS dependencies
WORKDIR /app
RUN python -m venv /opt/venv
RUN --mount=type=bind,source=requirements.runtime.txt,target=requirements.runtime.txt \
    --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install -r requirements.runtime.txt

FROM python:3.14.5-slim-bookworm AS runtime
ARG RELEASE_SHA=development
LABEL org.opencontainers.image.source="https://github.com/andruwka0/sverka" \
      org.opencontainers.image.revision=$RELEASE_SHA
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --no-create-home app
COPY --chown=1000:1000 radar ./radar
COPY --chown=1000:1000 frontend ./frontend
COPY --chown=1000:1000 rules.yaml ./rules.yaml
USER 1000:1000
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["uvicorn", "radar.main:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "8"]
