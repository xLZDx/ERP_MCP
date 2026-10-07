import { AsyncLocalStorage } from 'node:async_hooks';
import { createHash, timingSafeEqual } from 'node:crypto';
import { createServer } from 'node:http';
import { fetch as dispatcherFetch } from 'undici';
import { pinnedAgent } from './egress.mjs';
import { ODataV3Client, BasicAuth } from '@1c-odata/client';
import { raw } from '@1c-odata/client/filter';
import {
  fetchMetadataXml,
  groupFunctionImportsByEntitySet,
  parseEdmx,
} from '../../metadata/dist/index.js';

const DEFAULTS = Object.freeze({
  maxRequestBytes: 64 * 1024,
  maxResponseBytes: 5_000_000,
  maxMetadataBytes: 20_000_000,
  maxRows: 200,
  maxFilterChars: 4_000,
  timeoutMs: 30_000,
  maxSourceConcurrency: 4,
  circuitFailureThreshold: 5,
  circuitResetMs: 10_000,
});

const FETCH_BUDGET = Symbol.for('erp-mcp.odata-sidecar.fetch-budget');
const fetchBudgetStorage = new AsyncLocalStorage();

if (!globalThis[FETCH_BUDGET]) {
  const nativeFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = async (...args) => {
    const budget = fetchBudgetStorage.getStore();
    if (!budget) return nativeFetch(...args);
    const target = new URL(typeof args[0] === 'string' || args[0] instanceof URL ? args[0] : args[0].url);
    if (target.origin !== budget.allowedOrigin) throw new SidecarError(403, 'UPSTREAM_ORIGIN_DENIED');
    const response = await dispatcherFetch(args[0], { ...args[1], redirect: 'error',
      ...(budget.dispatcher ? { dispatcher: budget.dispatcher } : {}) });
    const declaredLength = Number(response.headers.get('content-length'));
    if (Number.isFinite(declaredLength) && declaredLength > budget.maxBytes - budget.usedBytes) {
      await response.body?.cancel();
      throw new SidecarError(502, 'UPSTREAM_RESPONSE_TOO_LARGE');
    }
    if (!response.body || response.status === 204 || response.status === 304) return response;

    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > budget.maxBytes - budget.usedBytes) {
        await reader.cancel();
        throw new SidecarError(502, 'UPSTREAM_RESPONSE_TOO_LARGE');
      }
      chunks.push(value);
    }
    budget.usedBytes += size;
    const headers = new Headers(response.headers);
    headers.delete('content-length');
    headers.delete('content-encoding');
    return new Response(Buffer.concat(chunks.map((chunk) => Buffer.from(chunk))), {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  };
  globalThis[FETCH_BUDGET] = true;
}

const IDENTIFIER = /^[\p{L}_][\p{L}\p{N}_]*$/u;
const ORDER_FIELD = /^([\p{L}_][\p{L}\p{N}_]*)(?:\s+(asc|desc))?$/iu;
const REGISTER_METHODS = Object.freeze({
  Accumulation: ['records', 'recordsets', 'balance', 'turnovers', 'balanceAndTurnovers'],
  Information: ['records', 'recordsets', 'sliceFirst', 'sliceLast'],
  Accounting: [
    'records', 'recordsets', 'balance', 'turnovers', 'balanceAndTurnovers',
    'drCrTurnovers', 'extDimensions', 'recordsWithExtDimensions',
  ],
});
const REGISTER_FUNCTIONS = Object.freeze({
  balance: 'Balance',
  turnovers: 'Turnovers',
  balanceAndTurnovers: 'BalanceAndTurnovers',
  sliceFirst: 'SliceFirst',
  sliceLast: 'SliceLast',
  drCrTurnovers: 'DrCrTurnovers',
  extDimensions: 'ExtDimensions',
  recordsWithExtDimensions: 'RecordsWithExtDimensions',
});

function buildRegisterCapabilityProfile(sourceId, metadataXml) {
  const model = parseEdmx(metadataXml);
  const metadataFingerprint = createHash('sha256').update(metadataXml).digest('hex');
  const byEntitySet = groupFunctionImportsByEntitySet(model.entityContainer.functionImports);
  const registers = model.entityContainer.entitySets.flatMap(({ name }) => {
    const match = /^(Accumulation|Information|Accounting)Register_/u.exec(name);
    if (!match) return [];
    const methods = {};
    for (const method of REGISTER_METHODS[match[1]]) {
      if (method === 'records' || method === 'recordsets') {
        methods[method] = {
          available: true,
          evidence: { kind: 'metadata-entity-set', entity_set: name, metadata_fingerprint: metadataFingerprint },
        };
        continue;
      }
      const functionName = REGISTER_FUNCTIONS[method];
      const binding = (byEntitySet.get(name) ?? []).find((item) =>
        item.name === functionName && item.entitySetPath === name && item.httpMethod === 'GET');
      methods[method] = binding
        ? {
          available: true,
          evidence: {
            kind: 'metadata-get-function-import',
            entity_set: name,
            function_import: functionName,
            http_method: 'GET',
            metadata_fingerprint: metadataFingerprint,
          },
        }
        : {
          available: false,
          evidence: {
            kind: 'metadata-function-import-absent-or-not-read-only',
            entity_set: name,
            function_import: functionName,
            metadata_fingerprint: metadataFingerprint,
          },
        };
    }
    return [{ entity_set: name, register_kind: match[1], methods }];
  });
  return {
    schema_version: 1,
    source_id: sourceId,
    evidence_source: 'live-metadata',
    discovered_at: new Date().toISOString(),
    metadata_fingerprint: metadataFingerprint,
    registers,
  };
}

export class SidecarError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

function findSidecarError(error) {
  const visited = new Set();
  let current = error;
  while (current && !visited.has(current)) {
    if (current instanceof SidecarError) return current;
    visited.add(current);
    current = current.cause;
  }
  return undefined;
}

function tokenMatches(expected, supplied) {
  if (typeof expected !== 'string' || typeof supplied !== 'string') return false;
  const left = Buffer.from(expected, 'utf8');
  const right = Buffer.from(supplied, 'utf8');
  return left.length === right.length && timingSafeEqual(left, right);
}

function bearerToken(header) {
  const match = typeof header === 'string' && /^Bearer ([^\s]+)$/.exec(header);
  return match?.[1];
}

async function readJson(req, limit) {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > limit) throw new SidecarError(413, 'REQUEST_TOO_LARGE');
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw new SidecarError(400, 'INVALID_JSON');
  }
}

function validateInput(input, allowedHosts, limits) {
  const keys = new Set([
    'operation', 'source_id', 'base_url', 'username', 'password', 'entity_set', 'key',
    'register_set', 'register_method', 'register_args',
    'select', 'filter', 'orderby', 'expand', 'top', 'skip',
  ]);
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new SidecarError(400, 'INVALID_REQUEST');
  }
  if (Object.keys(input).some((key) => !keys.has(key))) {
    throw new SidecarError(400, 'UNKNOWN_REQUEST_FIELD');
  }
  if (!['query', 'count', 'entity_get', 'register_read'].includes(input.operation)) {
    throw new SidecarError(400, 'OPERATION_NOT_ALLOWED');
  }
  if (typeof input.source_id !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(input.source_id)) {
    throw new SidecarError(400, 'INVALID_SOURCE_ID');
  }
  if (typeof input.base_url !== 'string' || input.base_url.length > 2048) {
    throw new SidecarError(400, 'INVALID_SOURCE_URL');
  }
  let url;
  try {
    url = new URL(input.base_url);
  } catch {
    throw new SidecarError(400, 'INVALID_SOURCE_URL');
  }
  if (
    !['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
    url.search || url.hash || !allowedHosts.has(url.host.toLowerCase())
  ) {
    throw new SidecarError(403, 'SOURCE_HOST_NOT_ALLOWED');
  }
  if (typeof input.username !== 'string' || !input.username || input.username.length > 512 ||
      typeof input.password !== 'string' || !input.password || input.password.length > 4096) {
    throw new SidecarError(400, 'INVALID_CREDENTIALS');
  }
  if (typeof input.entity_set !== 'string' || input.entity_set.length > 256 ||
      !IDENTIFIER.test(input.entity_set) || input.entity_set.startsWith('$')) {
    throw new SidecarError(400, 'INVALID_ENTITY_SET');
  }
  if (input.operation === 'entity_get') {
    const validKey = typeof input.key === 'string'
      ? /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(input.key)
      : input.key && typeof input.key === 'object' && !Array.isArray(input.key) &&
        Object.keys(input.key).length > 0 && Object.keys(input.key).length <= 8 &&
        Object.entries(input.key).every(([name, value]) => IDENTIFIER.test(name) &&
          typeof value === 'string' && value.length > 0 && value.length <= 512);
    if (!validKey) throw new SidecarError(400, 'INVALID_ENTITY_KEY');
  } else if (input.key !== undefined) {
    throw new SidecarError(400, 'INVALID_ENTITY_KEY');
  }
  if (input.operation === 'register_read') {
    const registerSet = input.register_set;
    const prefix = typeof registerSet === 'string' && registerSet.match(/^(Accumulation|Information|Accounting)Register_/u)?.[1];
    if (!prefix || registerSet.length > 256 || !IDENTIFIER.test(registerSet)) {
      throw new SidecarError(400, 'INVALID_REGISTER_SET');
    }
    if (typeof input.register_method !== 'string' || !REGISTER_METHODS[prefix].includes(input.register_method)) {
      throw new SidecarError(422, 'CAPABILITY_UNSUPPORTED');
    }
    const args = input.register_args ?? {};
    const rangeMethods = ['turnovers', 'balanceAndTurnovers', 'drCrTurnovers', 'recordsWithExtDimensions'];
    const allowedArgsByMethod = {
      balance: ['Period', 'Condition', 'Dimensions', 'AccountCondition', 'ExtraDimensions'],
      turnovers: ['Period', 'Condition', 'Dimensions', 'AccountCondition', 'ExtraDimensions'],
      balanceAndTurnovers: ['Period', 'Condition', 'Dimensions', 'AccountCondition', 'ExtraDimensions'],
      drCrTurnovers: [
        'Period', 'Condition', 'Dimensions', 'AccountCondition', 'BalancedAccountCondition',
        'ExtraDimensions', 'BalancedExtraDimensions',
      ],
      sliceFirst: ['Period', 'Condition'],
      sliceLast: ['Period', 'Condition'],
      extDimensions: [],
      recordsWithExtDimensions: ['Period', 'Condition', 'Order', 'Top'],
      records: [],
      recordsets: [],
    };
    const allowedArgs = new Set(allowedArgsByMethod[input.register_method]);
    if (!args || typeof args !== 'object' || Array.isArray(args) ||
        Object.keys(args).some((key) => !allowedArgs.has(key))) {
      throw new SidecarError(400, 'INVALID_REGISTER_ARGS');
    }
    if (rangeMethods.includes(input.register_method) && !args.Period) {
      throw new SidecarError(400, 'REGISTER_PERIOD_REQUIRED');
    }
    if (prefix !== 'Accounting' && (
      'AccountCondition' in args || 'BalancedAccountCondition' in args ||
      'ExtraDimensions' in args || 'BalancedExtraDimensions' in args
    )) {
      throw new SidecarError(400, 'INVALID_REGISTER_ARGS');
    }
    if (!['recordsets', 'records'].includes(input.register_method) && input.skip !== undefined && input.skip !== 0) {
      throw new SidecarError(400, 'INVALID_REGISTER_ARGS');
    }
    for (const [key, value] of Object.entries(args)) {
      if (['Condition', 'Dimensions', 'AccountCondition', 'BalancedAccountCondition', 'ExtraDimensions', 'BalancedExtraDimensions', 'Order'].includes(key) &&
          (typeof value !== 'string' || value.length > limits.maxFilterChars || /[\u0000-\u001f]/.test(value))) {
        throw new SidecarError(400, 'INVALID_REGISTER_ARGS');
      }
    }
    if (args.Top !== undefined && (!Number.isSafeInteger(args.Top) || args.Top < 1 || args.Top > limits.maxRows)) {
      throw new SidecarError(400, 'INVALID_REGISTER_ARGS');
    }
    if (args.Period !== undefined) {
      const dateValue = (value) => typeof value === 'string' &&
        /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?(?:Z|[+-]\d{2}:\d{2})$/u.test(value) &&
        !Number.isNaN(Date.parse(value));
      const rangeMethod = [
        'turnovers', 'balanceAndTurnovers', 'drCrTurnovers', 'recordsWithExtDimensions',
      ].includes(input.register_method);
      const validPeriod = rangeMethod
        ? args.Period && typeof args.Period === 'object' && !Array.isArray(args.Period) &&
          Object.keys(args.Period).length > 0 && Object.keys(args.Period).every((key) => ['from', 'to'].includes(key)) &&
          Object.values(args.Period).every(dateValue)
        : dateValue(args.Period);
      if (!validPeriod) throw new SidecarError(400, 'INVALID_REGISTER_PERIOD');
    }
    input.register_args = args;
  } else if (input.register_set !== undefined || input.register_method !== undefined || input.register_args !== undefined) {
    throw new SidecarError(400, 'INVALID_REGISTER_ARGS');
  }

  const select = input.select ?? [];
  const expand = input.expand ?? [];
  if (!Array.isArray(select) || select.length > 100 || select.some((field) =>
    typeof field !== 'string' || field.length > 256 || !IDENTIFIER.test(field))) {
    throw new SidecarError(400, 'INVALID_SELECT');
  }
  if (!Array.isArray(expand) || expand.length > 20 || expand.some((field) =>
    typeof field !== 'string' || field.length > 256 || !IDENTIFIER.test(field))) {
    throw new SidecarError(400, 'INVALID_EXPAND');
  }
  if (input.operation === 'register_read' && !['recordsets', 'records'].includes(input.register_method) &&
      (select.length || expand.length || input.filter || (input.orderby?.length ?? 0) > 0)) {
    throw new SidecarError(400, 'INVALID_REGISTER_ARGS');
  }
  if (input.filter != null && (typeof input.filter !== 'string' ||
      input.filter.length > limits.maxFilterChars || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(input.filter))) {
    throw new SidecarError(400, 'INVALID_FILTER');
  }

  const orderby = input.orderby ?? [];
  if (!Array.isArray(orderby) || orderby.length > 20) {
    throw new SidecarError(400, 'INVALID_ORDERBY');
  }
  const parsedOrder = orderby.map((item) => {
    if (typeof item !== 'string' || item.length > 300) throw new SidecarError(400, 'INVALID_ORDERBY');
    const match = ORDER_FIELD.exec(item.trim());
    if (!match) throw new SidecarError(400, 'INVALID_ORDERBY');
    return [match[1], (match[2] ?? 'asc').toLowerCase()];
  });

  const top = input.top ?? limits.maxRows;
  const skip = input.skip ?? 0;
  if (!Number.isSafeInteger(top) || top < 1 || top > limits.maxRows ||
      !Number.isSafeInteger(skip) || skip < 0 || skip > 1_000_000) {
    throw new SidecarError(400, 'INVALID_PAGE');
  }
  return { ...input, url, select, expand, parsedOrder, top, skip };
}

function validateCapabilitiesInput(input, allowedHosts) {
  const keys = new Set(['source_id', 'base_url', 'username', 'password']);
  if (!input || typeof input !== 'object' || Array.isArray(input) ||
      Object.keys(input).some((key) => !keys.has(key))) {
    throw new SidecarError(400, 'INVALID_CAPABILITY_REQUEST');
  }
  if (typeof input.source_id !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/u.test(input.source_id) ||
      typeof input.base_url !== 'string' || input.base_url.length > 2048) {
    throw new SidecarError(400, 'INVALID_CAPABILITY_REQUEST');
  }
  let url;
  try {
    url = new URL(input.base_url);
  } catch {
    throw new SidecarError(400, 'INVALID_SOURCE_URL');
  }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash ||
      !allowedHosts.has(url.host.toLowerCase())) {
    throw new SidecarError(403, 'SOURCE_HOST_NOT_ALLOWED');
  }
  if (typeof input.username !== 'string' || !input.username || input.username.length > 512 ||
      typeof input.password !== 'string' || !input.password || input.password.length > 4096) {
    throw new SidecarError(400, 'INVALID_CREDENTIALS');
  }
  return { ...input, url };
}

function buildClient(input, timeoutMs) {
  return new ODataV3Client({
    baseUrl: input.url.toString().replace(/\/$/, ''),
    auth: BasicAuth({ username: input.username, password: input.password }),
    // Preserve wire date strings: an unknown timezone must never be guessed.
    serverTimezone: 'UTC',
    shape: { dateMode: 'string', int64Mode: 'string' },
    timeout: timeoutMs,
  });
}

function serializeBounded(envelope, maxBytes) {
  let encoded = JSON.stringify(envelope);
  while (Buffer.byteLength(encoded, 'utf8') > maxBytes && envelope.data.length > 0) {
    envelope.data.pop();
    envelope.page.returned = envelope.data.length;
    envelope.page.truncated = true;
    envelope.page.has_more = true;
    encoded = JSON.stringify(envelope);
  }
  if (Buffer.byteLength(encoded, 'utf8') > maxBytes) {
    throw new SidecarError(502, 'RESPONSE_TOO_LARGE');
  }
  return encoded;
}

export function createHandler({
  token,
  allowedHosts,
  clientFactory = buildClient,
  metadataProvider = fetchMetadataXml,
  limits = {},
  egressCidrs = [],
  now = () => performance.now(),
} = {}) {
  const config = { ...DEFAULTS, ...limits };
  const dispatcher = egressCidrs.length ? pinnedAgent(egressCidrs) : undefined;
  const hostSet = new Set([...allowedHosts ?? []].map((host) => String(host).toLowerCase()));
  const inFlight = new Map();
  const circuits = new Map();
  const registerCapabilityCache = new Map();

  if (typeof token !== 'string' || Buffer.byteLength(token, 'utf8') < 32) {
    throw new Error('SIDECAR_TOKEN must contain at least 32 bytes');
  }
  if (hostSet.size === 0) throw new Error('ONEC_ALLOWED_HOSTS must contain at least one host');

  return async function handler(req, res) {
    if (req.method === 'GET' && req.url === '/healthz') {
      res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
      res.end(JSON.stringify({ status: 'ok', read_only: true }));
      return;
    }
    const capabilityRequest = req.url === '/v1/capabilities/registers' && req.method === 'POST';
    if (!capabilityRequest && !(req.url === '/v1/read' && req.method === 'POST')) {
      throw new SidecarError(404, 'NOT_FOUND');
    }
    if (!tokenMatches(token, bearerToken(req.headers.authorization))) {
      throw new SidecarError(401, 'UNAUTHORIZED');
    }
    if (!/^application\/json(?:\s*;|$)/i.test(req.headers['content-type'] ?? '')) {
      throw new SidecarError(415, 'JSON_REQUIRED');
    }

    const input = capabilityRequest
      ? validateCapabilitiesInput(await readJson(req, config.maxRequestBytes), hostSet)
      : validateInput(await readJson(req, config.maxRequestBytes), hostSet, config);
    if (capabilityRequest) input.operation = 'register_capabilities';
    const current = inFlight.get(input.source_id) ?? 0;
    if (current >= config.maxSourceConcurrency) throw new SidecarError(429, 'SOURCE_BUSY');
    const circuit = circuits.get(input.source_id);
    if (circuit?.openUntil > now()) throw new SidecarError(503, 'CIRCUIT_OPEN');
    inFlight.set(input.source_id, current + 1);

    const controller = new AbortController();
    const abortOnDisconnect = () => {
      if (!res.writableEnded) controller.abort();
    };
    req.once('aborted', abortOnDisconnect);
    res.once('close', abortOnDisconnect);
    const started = now();
    try {
      const client = clientFactory(input, config.timeoutMs);
      let data;
      let capabilityProfile;
      try {
        data = await fetchBudgetStorage.run(
          { maxBytes: config.maxResponseBytes, usedBytes: 0, dispatcher, allowedOrigin: input.url.origin },
          async () => {
            if (input.operation === 'register_capabilities' || input.operation === 'register_read') {
              const cacheKey = `${input.source_id}\u0000${input.url.toString()}`;
              let cached = registerCapabilityCache.get(cacheKey);
              if (!cached || cached.expiresAt <= Date.now()) {
                try {
                  const xml = await fetchBudgetStorage.run(
                    { maxBytes: config.maxMetadataBytes, usedBytes: 0, dispatcher, allowedOrigin: input.url.origin },
                    () => metadataProvider({
                      baseUrl: input.url.toString().replace(/\/$/u, ''),
                      auth: BasicAuth({ username: input.username, password: input.password }),
                      timeout: config.timeoutMs,
                      signal: controller.signal,
                    }),
                  );
                  cached = {
                    profile: buildRegisterCapabilityProfile(input.source_id, xml),
                    expiresAt: Date.now() + 30_000,
                  };
                  if (registerCapabilityCache.size >= 256) {
                    registerCapabilityCache.delete(registerCapabilityCache.keys().next().value);
                  }
                  registerCapabilityCache.set(cacheKey, cached);
                } catch {
                  throw new SidecarError(502, 'REGISTER_CAPABILITY_UNAVAILABLE');
                }
              }
              capabilityProfile = cached.profile;
              if (input.operation === 'register_capabilities') return [];
            }
            if (input.operation === 'entity_get') {
              const entity = await client.entity(input.entity_set, input.key).get({
                signal: controller.signal,
                timeout: config.timeoutMs,
              });
              return [entity];
            }
            if (input.operation === 'register_read') {
              const register = capabilityProfile.registers.find(
                (item) => item.entity_set === input.register_set,
              );
              const methodEvidence = register?.methods?.[input.register_method];
              if (!methodEvidence?.available) {
                throw new SidecarError(422, 'CAPABILITY_UNSUPPORTED');
              }
              const registerClient = client.register(input.register_set);
              let result;
              if (input.register_method === 'recordsets' || input.register_method === 'records') {
                let query = registerClient[input.register_method]().top(input.top).skip(input.skip);
                if (input.select.length) query = query.select(...input.select);
                if (input.filter) query = query.filter(() => raw(input.filter));
                const page = await query.get({ signal: controller.signal, timeout: config.timeoutMs });
                result = page.value;
              } else {
                const args = { ...input.register_args };
                if (args.Period && typeof args.Period === 'object') {
                  args.Period = {
                    ...(args.Period.from ? { from: new Date(args.Period.from) } : {}),
                    ...(args.Period.to ? { to: new Date(args.Period.to) } : {}),
                  };
                } else if (args.Period) {
                  args.Period = new Date(args.Period);
                }
                result = await registerClient[input.register_method](args, {
                  top: input.top,
                  signal: controller.signal,
                  timeout: config.timeoutMs,
                });
              }
              return Array.isArray(result) ? result.slice(0, input.top) : [];
            }
            let builder = client.query(input.entity_set).top(input.top).skip(input.skip);
            if (input.select.length) builder = builder.select(...input.select);
            if (input.filter) builder = builder.filter(() => raw(input.filter));
            for (const [field, direction] of input.parsedOrder) builder = builder.orderBy(field, direction);
            for (const field of input.expand) builder = builder.expand(field);
            if (input.operation === 'count') {
              const count = await builder.count({ signal: controller.signal, timeout: config.timeoutMs });
              return [{ count }];
            }
            const page = await builder.get({ signal: controller.signal, timeout: config.timeoutMs });
            return Array.isArray(page.value) ? page.value.slice(0, input.top) : [];
          },
        );
        circuits.delete(input.source_id);
      } catch (error) {
        const failures = (circuits.get(input.source_id)?.failures ?? 0) + 1;
        circuits.set(input.source_id, {
          failures,
          openUntil: failures >= config.circuitFailureThreshold
            ? now() + config.circuitResetMs
            : 0,
        });
        throw findSidecarError(error) ?? error;
      }
      const returned = data.length;
      const envelope = {
        source_id: input.source_id,
        adapter: { kind: 'ODATA_JSON_V3', version: '0.6.0', upstream_sha: process.env.ODATA_UPSTREAM_SHA ?? 'cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5' },
        operation: input.operation,
        data,
        ...(capabilityProfile ? { capability_profile: capabilityProfile } : {}),
        page: {
          returned,
          has_more: ['query', 'register_read'].includes(input.operation) && returned === input.top,
          truncated: false,
        },
        timing: { upstream_ms: Math.max(0, Math.round(now() - started)) },
      };
      const body = serializeBounded(envelope, config.maxResponseBytes);
      if (!res.writableEnded) {
        res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
        res.end(body);
      }
    } finally {
      req.off('aborted', abortOnDisconnect);
      res.off('close', abortOnDisconnect);
      const remaining = (inFlight.get(input.source_id) ?? 1) - 1;
      if (remaining === 0) inFlight.delete(input.source_id);
      else inFlight.set(input.source_id, remaining);
    }
  };
}

export function startFromEnvironment() {
  const token = process.env.SIDECAR_TOKEN;
  const allowedHosts = (process.env.ONEC_ALLOWED_HOSTS ?? '').split(',').map((host) => host.trim()).filter(Boolean);
  const egressCidrs = (process.env.ONEC_EGRESS_CIDRS ?? '').split(',').map((item) => item.trim()).filter(Boolean);
  if (process.env.NODE_ENV === 'production' && egressCidrs.length === 0) throw new Error('ONEC_EGRESS_CIDRS_REQUIRED');
  const server = createServer((req, res) => {
    void createHandlerSingleton(req, res);
  });
  const handler = createHandler({ token, allowedHosts, egressCidrs });
  async function createHandlerSingleton(req, res) {
    try {
      await handler(req, res);
    } catch (error) {
      if (res.headersSent || res.writableEnded) return;
      const status = error instanceof SidecarError ? error.status : 502;
      const code = error instanceof SidecarError ? error.code : 'UPSTREAM_ERROR';
      res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
      res.end(JSON.stringify({ error: { code } }));
    }
  }
  const port = Number(process.env.PORT ?? 8765);
  server.listen(port, '0.0.0.0');
  return server;
}

if (process.argv[1] && new URL(import.meta.url).pathname === process.argv[1].replaceAll('\\', '/')) {
  startFromEnvironment();
}
