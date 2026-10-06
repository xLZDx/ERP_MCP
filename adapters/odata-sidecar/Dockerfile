ARG NODE_BUILD_IMAGE=node:24.18.0-alpine@sha256:a0b9bf06e4e6193cf7a0f58816cc935ff8c2a908f81e6f1a95432d679c54fbfd

FROM ${NODE_BUILD_IMAGE} AS build
WORKDIR /build/upstream

COPY vendor/reference/1c-odata-v3/ ./
COPY adapters/odata-sidecar/ ./packages/client/sidecar/

RUN corepack enable \
 && pnpm install --frozen-lockfile \
 && npm ci --prefix packages/client/sidecar --omit=dev --ignore-scripts \
 && pnpm --filter @1c-odata/client build \
 && pnpm --filter @1c-odata/metadata build \
 && pnpm --filter @1c-odata/metadata deploy --prod --legacy /build/runtime

FROM cgr.dev/chainguard/node:latest@sha256:af9d762479c010649ab93b6ba2b0580522956d30c15043b61b00dea5743c9096 AS runtime
ARG ODATA_UPSTREAM_SHA=cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5
ENV NODE_ENV=production PORT=8765

WORKDIR /app
COPY --from=build --chown=10001:10001 /build/upstream/packages/client/package.json ./packages/client/package.json
COPY --from=build --chown=10001:10001 /build/upstream/packages/client/dist ./packages/client/dist
COPY --from=build --chown=10001:10001 /build/upstream/packages/client/sidecar/*.mjs ./packages/client/sidecar/
COPY --from=build --chown=10001:10001 /build/upstream/packages/metadata/package.json ./packages/metadata/package.json
COPY --from=build --chown=10001:10001 /build/upstream/packages/metadata/dist ./packages/metadata/dist
COPY --from=build --chown=10001:10001 /build/runtime/node_modules ./node_modules
COPY --from=build --chown=10001:10001 /build/upstream/packages/client/sidecar/node_modules/undici ./node_modules/undici

LABEL org.opencontainers.image.title="ERP_MCP read-only OData sidecar" \
      org.opencontainers.image.version="0.6.0" \
      org.opencontainers.image.revision="${ODATA_UPSTREAM_SHA}" \
      org.opencontainers.image.licenses="MIT"

USER 65532:65532
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["/usr/bin/node", "-e", "fetch('http://127.0.0.1:8765/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]

CMD ["packages/client/sidecar/server.mjs"]
