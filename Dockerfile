FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid 10001 --create-home app

WORKDIR /app
COPY pyproject.toml README.md SECURITY.md ./
COPY src ./src
RUN python -m pip install --upgrade pip \
 && python -m pip install .

COPY db ./db
COPY scripts ./scripts

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["uvicorn", "business_ai_gateway.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
