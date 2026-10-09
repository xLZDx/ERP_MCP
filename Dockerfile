FROM python:3.14-slim-trixie@sha256:3353bb7e9ae99c7cce6cad2b2f2b174e8f22813ac43e3b13e7a742627d2b01d8 AS dependencies

ENV PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements-runtime.lock ./
RUN python -m pip install --require-hashes --target=/runtime-deps -r requirements-runtime.lock

FROM cgr.dev/chainguard/python:latest@sha256:b6248c85ba9b97e1e61b30197f309cc4d21661f889fefa5268f0a7bc530dad46
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src:/usr/lib/python3.14/site-packages
WORKDIR /app
COPY --from=dependencies /runtime-deps/ /usr/lib/python3.14/site-packages/
COPY src ./src

COPY db ./db
COPY scripts ./scripts

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["/usr/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

CMD ["-m", "uvicorn", "business_ai_gateway.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
