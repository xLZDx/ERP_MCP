import { lookup } from 'node:dns/promises';
import { BlockList, isIP } from 'node:net';
import { Agent, buildConnector } from 'undici';

export function guardedLookup(cidrs, resolver = lookup) {
  const allowed = new BlockList();
  for (const cidr of cidrs) {
    const [address, rawPrefix, extra] = cidr.split('/');
    const family = isIP(address);
    const prefix = Number(rawPrefix);
    if (!family || extra !== undefined || rawPrefix === undefined || !Number.isInteger(prefix) ||
        prefix < 0 || prefix > (family === 4 ? 32 : 128)) {
      throw new Error('INVALID_EGRESS_POLICY');
    }
    allowed.addSubnet(address, prefix, family === 4 ? 'ipv4' : 'ipv6');
  }
  if (cidrs.length === 0) throw new Error('EGRESS_POLICY_REQUIRED');
  return (hostname, options, callback) => {
    const numericFamily = isIP(hostname);
    const resolved = numericFamily
      ? Promise.resolve([{ address: hostname, family: numericFamily }])
      : resolver(hostname, { all: true, verbatim: true });
    void resolved.then((answers) => {
      if (!Array.isArray(answers) || answers.length === 0 || answers.length > 64 ||
          answers.some((item) => !item || typeof item.address !== 'string' || ![4, 6].includes(item.family) ||
            isIP(item.address) !== item.family || !allowed.check(item.address, item.family === 4 ? 'ipv4' : 'ipv6'))) {
        callback(new Error('EGRESS_DESTINATION_DENIED'));
        return;
      }
      const requestedFamily = typeof options === 'number' ? options : options?.family;
      const filtered = requestedFamily ? answers.filter((item) => item.family === requestedFamily) : answers;
      if (filtered.length === 0) return callback(new Error('EGRESS_ADDRESS_FAMILY_UNAVAILABLE'));
      if (options?.all) callback(null, filtered);
      else callback(null, filtered[0].address, filtered[0].family);
    }, () => callback(new Error('EGRESS_RESOLUTION_FAILED')));
  };
}

export function pinnedAgent(cidrs) {
  const resolve = guardedLookup(cidrs);
  const connect = buildConnector({});
  return new Agent({ connect(options, callback) {
    resolve(options.hostname, { all: true }, (error, addresses) => {
      if (error) return callback(error);
      connect({ ...options, hostname: addresses[0].address,
        servername: options.servername || (isIP(options.hostname) ? undefined : options.hostname) }, callback);
    });
  } });
}
