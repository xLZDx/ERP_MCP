import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import test from 'node:test';
import { guardedLookup, pinnedAgent } from './egress.mjs';

function resolve(fn, host) {
  return new Promise((done, reject) => fn(host, { all: true }, (error, answers) =>
    error ? reject(error) : done(answers)));
}

test('DNS addresses are pinned and mixed/rebound answers fail closed', async () => {
  const good = guardedLookup(['192.0.2.0/24'], async () => [{ address: '192.0.2.8', family: 4 }]);
  assert.deepEqual(await resolve(good, 'registered.test'), [{ address: '192.0.2.8', family: 4 }]);
  const mixed = guardedLookup(['192.0.2.0/24'], async () => [
    { address: '192.0.2.8', family: 4 }, { address: '127.0.0.1', family: 4 },
  ]);
  await assert.rejects(resolve(mixed, 'registered.test'), /EGRESS_DESTINATION_DENIED/);
  await assert.rejects(resolve(good, '127.0.0.1'), /EGRESS_DESTINATION_DENIED/);
  await assert.rejects(resolve(good, '::1'), /EGRESS_DESTINATION_DENIED/);
});

test('numeric host cannot bypass the actual Agent policy', async () => {
  let requests = 0;
  const server = createServer((_req, res) => { requests++; res.end('ok'); });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const denied = pinnedAgent(['192.0.2.0/24']);
  const allowed = pinnedAgent(['127.0.0.1/32']);
  const url = `http://127.0.0.1:${server.address().port}/`;
  try {
    await assert.rejects(fetch(url, { dispatcher: denied }));
    assert.equal(requests, 0);
    const result = await fetch(url, { dispatcher: allowed });
    assert.equal(await result.text(), 'ok');
    assert.equal(requests, 1);
  } finally {
    await Promise.all([denied.close(), allowed.close()]);
    server.close();
    await once(server, 'close');
  }
});
