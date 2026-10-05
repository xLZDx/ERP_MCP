import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer } from 'node:http';
import test from 'node:test';

import { createHandler } from './server.mjs';

const TOKEN = 'test-sidecar-token-with-at-least-thirty-two-bytes';

async function withServer(handler, run) {
  const server = createServer(async (req, res) => {
    try {
      await handler(req, res);
    } catch (error) {
      const status = Number.isInteger(error.status) ? error.status : 502;
      res.writeHead(status, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: { code: error.code ?? 'UPSTREAM_ERROR' } }));
    }
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    server.close();
    await once(server, 'close');
  }
}

function requestBody(overrides = {}) {
  return {
    operation: 'query',
    source_id: 'source-1',
    base_url: 'https://onec.example.test/odata/standard.odata',
    username: 'readonly',
    password: 'secret-value',
    entity_set: 'Catalog_Items',
    select: ['Ref_Key', 'Description'],
    filter: "Description eq 'test'",
    orderby: ['Description desc'],
    expand: [],
    top: 2,
    skip: 0,
    ...overrides,
  };
}

function fakeClientFactory({ values = [], count = 0, calls = [] } = {}) {
  return (input, timeout) => {
    calls.push({ input, timeout });
    const builder = {
      top(value) { calls.push(['top', value]); return this; },
      skip(value) { calls.push(['skip', value]); return this; },
      select(...value) { calls.push(['select', value]); return this; },
      filter(value) { calls.push(['filter', value({})._expr]); return this; },
      orderBy(...value) { calls.push(['orderBy', value]); return this; },
      expand(value) { calls.push(['expand', value]); return this; },
      async get(options) { calls.push(['get', options]); return { value: values }; },
      async count(options) { calls.push(['count', options]); return count; },
    };
    return { query: (entitySet) => { calls.push(['query', entitySet]); return builder; } };
  };
}

async function post(base, body, authorization = `Bearer ${TOKEN}`) {
  return fetch(`${base}/v1/read`, {
    method: 'POST',
    headers: { authorization, 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

test('read contract calls only the upstream query GET surface and returns provenance', async () => {
  const calls = [];
  const handler = createHandler({
    token: TOKEN,
    allowedHosts: ['onec.example.test'],
    clientFactory: fakeClientFactory({
      values: [{ Ref_Key: '1' }, { Ref_Key: '2' }, { Ref_Key: '3' }],
      calls,
    }),
  });

  await withServer(handler, async (base) => {
    const response = await post(base, requestBody());
    assert.equal(response.status, 200);
    const envelope = await response.json();
    assert.deepEqual(envelope.data, [{ Ref_Key: '1' }, { Ref_Key: '2' }]);
    assert.deepEqual(envelope.page, { returned: 2, has_more: true, truncated: false });
    assert.equal(envelope.source_id, 'source-1');
    assert.equal(envelope.adapter.upstream_sha, 'cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5');
    assert.ok(calls.some((call) => Array.isArray(call) && call[0] === 'get'));
    assert.ok(calls.some((call) => Array.isArray(call) && call[0] === 'filter'));
    assert.ok(calls.some((call) => Array.isArray(call) && call[0] === 'orderBy'));
    assert.ok(!calls.some((call) => Array.isArray(call) && call[0] === 'create'));
  });
});

test('count is an explicit read operation', async () => {
  const calls = [];
  const handler = createHandler({
    token: TOKEN,
    allowedHosts: ['onec.example.test'],
    clientFactory: fakeClientFactory({ count: 7, calls }),
  });

  await withServer(handler, async (base) => {
    const response = await post(base, requestBody({ operation: 'count' }));
    assert.equal(response.status, 200);
    const envelope = await response.json();
    assert.deepEqual(envelope.data, [{ count: 7 }]);
    assert.ok(calls.some((call) => Array.isArray(call) && call[0] === 'count'));
  });
});

test('entity_get calls only the upstream keyed GET handle', async () => {
  let keyReceived;
  const handler = createHandler({
    token: TOKEN,
    allowedHosts: ['onec.example.test'],
    clientFactory: () => ({
      query: () => { throw new Error('collection query must not run'); },
      entity: (entitySet, key) => {
        assert.equal(entitySet, 'Catalog_Items');
        keyReceived = key;
        return { get: async () => ({ Ref_Key: key }) };
      },
    }),
  });
  await withServer(handler, async (base) => {
    const response = await post(base, requestBody({
      operation: 'entity_get', key: '123e4567-e89b-12d3-a456-426614174000',
    }));
    assert.equal(response.status, 200);
    const envelope = await response.json();
    assert.deepEqual(envelope.data, [{ Ref_Key: '123e4567-e89b-12d3-a456-426614174000' }]);
    assert.deepEqual(keyReceived, '123e4567-e89b-12d3-a456-426614174000');

    const invalid = await post(base, requestBody({ operation: 'entity_get', key: "')/Orders" }));
    assert.equal(invalid.status, 400);
    assert.deepEqual(await invalid.json(), { error: { code: 'INVALID_ENTITY_KEY' } });
  });
});

test('register reads use only an allowlisted pinned read method with bounded arguments', async () => {
  let call;
  const metadata = `<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx" Version="1.0">
  <edmx:DataServices m:DataServiceVersion="3.0" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
    <Schema Namespace="StandardODATA" xmlns="http://schemas.microsoft.com/ado/2009/11/edm">
      <EntityType Name="AccumulationRegister_Inventory"><Key><PropertyRef Name="Ref_Key"/></Key><Property Name="Ref_Key" Type="Edm.Guid" Nullable="false"/></EntityType>
      <EntityContainer Name="StandardODATA">
        <EntitySet Name="AccumulationRegister_Inventory" EntityType="StandardODATA.AccumulationRegister_Inventory"/>
        <FunctionImport Name="Turnovers" IsBindable="true" m:HttpMethod="GET">
          <Parameter Name="bindingParameter" Type="StandardODATA.AccumulationRegister_Inventory"/>
        </FunctionImport>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>`;
  const handler = createHandler({
    token: TOKEN,
    allowedHosts: ['onec.example.test'],
    metadataProvider: async () => metadata,
    clientFactory: () => ({
      register: (name) => {
        assert.equal(name, 'AccumulationRegister_Inventory');
        return {
          turnovers: async (args, options) => {
            call = { args, options };
            return [{ Item_Key: 'i1', QuantityTurnover: '3' }];
          },
        };
      },
    }),
  });
  await withServer(handler, async (base) => {
    const response = await post(base, requestBody({
      operation: 'register_read',
      register_set: 'AccumulationRegister_Inventory',
      register_method: 'turnovers',
      register_args: { Period: { from: '2025-01-01T00:00:00Z', to: '2025-01-31T23:59:59Z' } },
      select: [], filter: null, orderby: [], expand: [],
    }));
    assert.equal(response.status, 200);
    const envelope = await response.json();
    assert.equal(envelope.data.length, 1);
    assert.ok(call.args.Period.from instanceof Date);
    assert.ok(call.args.Period.to instanceof Date);

    const mutation = await post(base, requestBody({
      operation: 'register_read', register_set: 'AccumulationRegister_Inventory',
      register_method: 'drCrTurnovers', register_args: {},
      select: [], filter: null, orderby: [], expand: [],
    }));
    assert.equal(mutation.status, 422);
    assert.deepEqual(await mutation.json(), { error: { code: 'CAPABILITY_UNSUPPORTED' } });

    const unbounded = await post(base, requestBody({
      operation: 'register_read', register_set: 'AccumulationRegister_Inventory',
      register_method: 'turnovers', register_args: {},
      select: [], filter: null, orderby: [], expand: [],
    }));
    assert.equal(unbounded.status, 400);
    assert.deepEqual(await unbounded.json(), { error: { code: 'REGISTER_PERIOD_REQUIRED' } });
  });
});

test('unauthorized and non-allowlisted requests never construct an OData client', async () => {
  let constructed = 0;
  const handler = createHandler({
    token: TOKEN,
    allowedHosts: ['onec.example.test'],
    clientFactory: () => { constructed++; throw new Error('must not run'); },
  });

  await withServer(handler, async (base) => {
    const unauthorized = await post(base, requestBody(), 'Bearer wrong-token');
    assert.equal(unauthorized.status, 401);
    assert.deepEqual(await unauthorized.json(), { error: { code: 'UNAUTHORIZED' } });

    const forbidden = await post(base, requestBody({ base_url: 'http://127.0.0.1:5432/' }));
    assert.equal(forbidden.status, 403);
    assert.deepEqual(await forbidden.json(), { error: { code: 'SOURCE_HOST_NOT_ALLOWED' } });
    assert.equal(constructed, 0);
  });
});

test('mutation-shaped operations, invalid fields and oversized output fail closed', async () => {
  const handler = createHandler({
    token: TOKEN,
    allowedHosts: ['onec.example.test'],
    limits: { maxResponseBytes: 400 },
    clientFactory: fakeClientFactory({ values: [{ Ref_Key: 'x', Description: 'x'.repeat(500) }] }),
  });

  await withServer(handler, async (base) => {
    const mutation = await post(base, requestBody({ operation: 'create' }));
    assert.equal(mutation.status, 400);
    assert.deepEqual(await mutation.json(), { error: { code: 'OPERATION_NOT_ALLOWED' } });

    const invalidSet = await post(base, requestBody({ entity_set: '../secret' }));
    assert.equal(invalidSet.status, 400);
    assert.deepEqual(await invalidSet.json(), { error: { code: 'INVALID_ENTITY_SET' } });

    const oversized = await post(base, requestBody({ select: [], filter: undefined, orderby: [] }));
    assert.equal(oversized.status, 200);
    const envelope = await oversized.json();
    assert.equal(envelope.data.length, 0);
    assert.equal(envelope.page.truncated, true);
  });
});

test('per-source circuit opens after repeated upstream failures and then permits a retry', async () => {
  let now = 0;
  let attempts = 0;
  const clientFactory = () => {
    const builder = {
      top() { return this; },
      skip() { return this; },
      select() { return this; },
      filter() { return this; },
      orderBy() { return this; },
      expand() { return this; },
      async get() { attempts++; throw new Error('sensitive upstream detail'); },
    };
    return { query: () => builder };
  };
  const handler = createHandler({
    token: TOKEN,
    allowedHosts: ['onec.example.test'],
    clientFactory,
    limits: { circuitFailureThreshold: 2, circuitResetMs: 100 },
    now: () => now,
  });

  await withServer(handler, async (base) => {
    const first = await post(base, requestBody());
    assert.equal(first.status, 502);
    assert.deepEqual(await first.json(), { error: { code: 'UPSTREAM_ERROR' } });
    const second = await post(base, requestBody());
    assert.equal(second.status, 502);
    assert.equal(attempts, 2);

    const open = await post(base, requestBody());
    assert.equal(open.status, 503);
    assert.deepEqual(await open.json(), { error: { code: 'CIRCUIT_OPEN' } });
    assert.equal(attempts, 2);

    now = 101;
    const retry = await post(base, requestBody());
    assert.equal(retry.status, 502);
    assert.equal(attempts, 3);
  });
});

test('upstream response body is capped before the OData parser buffers it', async () => {
  const upstream = createServer((_req, res) => {
    const body = JSON.stringify({ value: [{ Description: 'x'.repeat(2_000) }] });
    res.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) });
    res.end(body);
  });
  upstream.listen(0, '127.0.0.1');
  await once(upstream, 'listening');
  const upstreamUrl = `http://127.0.0.1:${upstream.address().port}/odata`;
  const handler = createHandler({
    token: TOKEN,
    allowedHosts: [`127.0.0.1:${upstream.address().port}`],
    limits: { maxResponseBytes: 512 },
  });

  try {
    await withServer(handler, async (base) => {
      const response = await post(base, requestBody({ base_url: upstreamUrl, select: [], filter: undefined, orderby: [] }));
      assert.equal(response.status, 502);
      assert.deepEqual(await response.json(), { error: { code: 'UPSTREAM_RESPONSE_TOO_LARGE' } });
    });
  } finally {
    upstream.close();
    await once(upstream, 'close');
  }
});

test('the pinned client performs a real read-only OData register request through the sidecar', async () => {
  const seen = [];
  const metadata = `<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx" Version="1.0">
  <edmx:DataServices m:DataServiceVersion="3.0" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
    <Schema Namespace="StandardODATA" xmlns="http://schemas.microsoft.com/ado/2009/11/edm">
      <EntityType Name="AccumulationRegister_Inventory"><Key><PropertyRef Name="Ref_Key"/></Key><Property Name="Ref_Key" Type="Edm.Guid" Nullable="false"/></EntityType>
      <EntityContainer Name="StandardODATA" m:IsDefaultEntityContainer="true">
        <EntitySet Name="AccumulationRegister_Inventory" EntityType="StandardODATA.AccumulationRegister_Inventory"/>
        <FunctionImport Name="Turnovers" IsBindable="true" m:HttpMethod="GET" ReturnType="Collection(StandardODATA.Inventory_Turnover)">
          <Parameter Name="bindingParameter" Type="StandardODATA.AccumulationRegister_Inventory"/>
        </FunctionImport>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>`;
  const upstream = createServer((req, res) => {
    seen.push(req.url);
    if (req.url === '/odata/standard.odata/$metadata') {
      res.writeHead(200, { 'content-type': 'application/xml' });
      res.end(metadata);
      return;
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ value: [{ QuantityTurnover: '3' }] }));
  });
  upstream.listen(0, '127.0.0.1');
  await once(upstream, 'listening');
  const authority = `127.0.0.1:${upstream.address().port}`;
  const handler = createHandler({ token: TOKEN, allowedHosts: [authority] });
  try {
    await withServer(handler, async (base) => {
      const response = await post(base, requestBody({
        operation: 'register_read',
        base_url: `http://${authority}/odata/standard.odata`,
        register_set: 'AccumulationRegister_Inventory',
        register_method: 'turnovers',
        register_args: { Period: { from: '2025-01-01T00:00:00Z', to: '2025-01-31T23:59:59Z' } },
        select: [], filter: null, orderby: [], expand: [],
      }));
      assert.equal(response.status, 200);
      const envelope = await response.json();
      assert.deepEqual(envelope.data, [{ QuantityTurnover: '3' }]);
      assert.equal(seen.length, 2);
      assert.equal(seen[0], '/odata/standard.odata/$metadata');
      assert.match(seen[1], /AccumulationRegister_Inventory\/Turnovers\(/u);
      assert.match(seen[1], /StartPeriod=/u);
      assert.match(seen[1], /EndPeriod=/u);
      const unsupported = await post(base, requestBody({
        operation: 'register_read',
        base_url: `http://${authority}/odata/standard.odata`,
        register_set: 'AccumulationRegister_Inventory',
        register_method: 'balance',
        register_args: { Period: '2025-01-31T23:59:59Z' },
        select: [], filter: null, orderby: [], expand: [],
      }));
      assert.equal(unsupported.status, 422);
      assert.deepEqual(await unsupported.json(), { error: { code: 'CAPABILITY_UNSUPPORTED' } });
      assert.equal(seen.length, 2, 'unpublished function must not reach the OData data endpoint');
      const drCrWrongRegister = await post(base, requestBody({
        operation: 'register_read',
        base_url: `http://${authority}/odata/standard.odata`,
        register_set: 'AccumulationRegister_Inventory',
        register_method: 'drCrTurnovers',
        register_args: { Period: { from: '2025-01-01T00:00:00Z' } },
        select: [], filter: null, orderby: [], expand: [],
      }));
      assert.equal(drCrWrongRegister.status, 422);
      assert.deepEqual(await drCrWrongRegister.json(), { error: { code: 'CAPABILITY_UNSUPPORTED' } });
      assert.equal(seen.length, 2, 'type-inapplicable virtual table must not reach the data endpoint');
    });
  } finally {
    upstream.close();
    await once(upstream, 'close');
  }
});

test('DrCrTurnovers is advertised and invoked only when the exact live binding is present', async () => {
  const seen = [];
  const metadata = `<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx" Version="1.0">
  <edmx:DataServices m:DataServiceVersion="3.0" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
    <Schema Namespace="StandardODATA" xmlns="http://schemas.microsoft.com/ado/2009/11/edm">
      <EntityType Name="AccountingRegister_Хозрасчетный"><Key><PropertyRef Name="Ref_Key"/></Key><Property Name="Ref_Key" Type="Edm.Guid" Nullable="false"/></EntityType>
      <EntityContainer Name="StandardODATA" m:IsDefaultEntityContainer="true">
        <EntitySet Name="AccountingRegister_Хозрасчетный" EntityType="StandardODATA.AccountingRegister_Хозрасчетный"/>
        <FunctionImport Name="DrCrTurnovers" IsBindable="true" m:HttpMethod="GET" ReturnType="Collection(StandardODATA.AccountingRegister_Хозрасчетный)">
          <Parameter Name="bindingParameter" Type="StandardODATA.AccountingRegister_Хозрасчетный"/>
        </FunctionImport>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>`;
  const upstream = createServer((req, res) => {
    seen.push(req.url);
    if (req.url === '/odata/standard.odata/$metadata') {
      res.writeHead(200, { 'content-type': 'application/xml' });
      res.end(metadata);
      return;
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ value: [{ Turnover: '8' }] }));
  });
  upstream.listen(0, '127.0.0.1');
  await once(upstream, 'listening');
  const authority = `127.0.0.1:${upstream.address().port}`;
  const handler = createHandler({ token: TOKEN, allowedHosts: [authority] });
  try {
    await withServer(handler, async (base) => {
      const capabilityResponse = await fetch(`${base}/v1/capabilities/registers`, {
        method: 'POST',
        headers: { authorization: `Bearer ${TOKEN}`, 'content-type': 'application/json' },
        body: JSON.stringify({
          source_id: 'source-1',
          base_url: `http://${authority}/odata/standard.odata`,
          username: 'readonly',
          password: 'secret-value',
        }),
      });
      assert.equal(capabilityResponse.status, 200);
      const capabilityEnvelope = await capabilityResponse.json();
      const profile = capabilityEnvelope.capability_profile;
      assert.equal(profile.evidence_source, 'live-metadata');
      assert.match(profile.metadata_fingerprint, /^[0-9a-f]{64}$/u);
      assert.equal(profile.registers[0].entity_set, 'AccountingRegister_Хозрасчетный');
      assert.equal(profile.registers[0].methods.drCrTurnovers.available, true);
      assert.equal(profile.registers[0].methods.drCrTurnovers.evidence.function_import, 'DrCrTurnovers');

      const readResponse = await post(base, requestBody({
        operation: 'register_read',
        base_url: `http://${authority}/odata/standard.odata`,
        entity_set: 'AccountingRegister_Хозрасчетный',
        register_set: 'AccountingRegister_Хозрасчетный',
        register_method: 'drCrTurnovers',
        register_args: {
          Period: { from: '2025-01-01T00:00:00Z', to: '2025-01-31T23:59:59Z' },
        },
        select: [], filter: null, orderby: [], expand: [],
      }));
      const readEnvelope = await readResponse.json();
      assert.equal(readResponse.status, 200, JSON.stringify(readEnvelope));
      assert.deepEqual(readEnvelope.data, [{ Turnover: '8' }]);
      assert.equal(seen.length, 2, 'metadata then one pinned-client GET; no speculative alternatives');
      assert.equal(seen[0], '/odata/standard.odata/$metadata');
      assert.match(decodeURIComponent(seen[1]), /AccountingRegister_Хозрасчетный\/DrCrTurnovers\(/u);
    });
  } finally {
    upstream.close();
    await once(upstream, 'close');
  }
});

test('missing DrCrTurnovers produces negative source evidence and no speculative OData call', async () => {
  const seen = [];
  const metadata = `<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx" Version="1.0">
  <edmx:DataServices m:DataServiceVersion="3.0" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
    <Schema Namespace="StandardODATA" xmlns="http://schemas.microsoft.com/ado/2009/11/edm">
      <EntityType Name="AccountingRegister_Ledger"><Key><PropertyRef Name="Ref_Key"/></Key><Property Name="Ref_Key" Type="Edm.Guid" Nullable="false"/></EntityType>
      <EntityContainer Name="StandardODATA" m:IsDefaultEntityContainer="true">
        <EntitySet Name="AccountingRegister_Ledger" EntityType="StandardODATA.AccountingRegister_Ledger"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>`;
  const upstream = createServer((req, res) => {
    seen.push(req.url);
    if (req.url === '/odata/standard.odata/$metadata') {
      res.writeHead(200, { 'content-type': 'application/xml' });
      res.end(metadata);
      return;
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ value: [{ ShouldNotBeRead: true }] }));
  });
  upstream.listen(0, '127.0.0.1');
  await once(upstream, 'listening');
  const authority = `127.0.0.1:${upstream.address().port}`;
  const handler = createHandler({ token: TOKEN, allowedHosts: [authority] });
  try {
    await withServer(handler, async (base) => {
      const capabilitiesResponse = await fetch(`${base}/v1/capabilities/registers`, {
        method: 'POST',
        headers: { authorization: `Bearer ${TOKEN}`, 'content-type': 'application/json' },
        body: JSON.stringify({
          source_id: 'source-1',
          base_url: `http://${authority}/odata/standard.odata`,
          username: 'readonly',
          password: 'secret-value',
        }),
      });
      const capabilityEnvelope = await capabilitiesResponse.json();
      assert.equal(capabilitiesResponse.status, 200);
      assert.equal(
        capabilityEnvelope.capability_profile.registers[0].methods.drCrTurnovers.available,
        false,
      );
      assert.equal(
        capabilityEnvelope.capability_profile.registers[0].methods.drCrTurnovers.evidence.kind,
        'metadata-function-import-absent-or-not-read-only',
      );

      const response = await post(base, requestBody({
        operation: 'register_read',
        base_url: `http://${authority}/odata/standard.odata`,
        entity_set: 'AccountingRegister_Ledger',
        register_set: 'AccountingRegister_Ledger',
        register_method: 'drCrTurnovers',
        register_args: { Period: { from: '2025-01-01T00:00:00Z' } },
        select: [], filter: null, orderby: [], expand: [],
      }));
      assert.equal(response.status, 422);
      assert.deepEqual(await response.json(), { error: { code: 'CAPABILITY_UNSUPPORTED' } });
      assert.deepEqual(seen, ['/odata/standard.odata/$metadata']);
    });
  } finally {
    upstream.close();
    await once(upstream, 'close');
  }
});
