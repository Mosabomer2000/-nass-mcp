/**
 * Nass MCP — authenticated Streamable HTTP gateway.
 * The actual MCP protocol is implemented by the Python Nass upstream; this function
 * deliberately forwards JSON-RPC messages verbatim instead of reimplementing MCP.
 * Netlify cannot run CPU-heavy Whisper ASR within its function runtime.
 */
import { timingSafeEqual } from 'node:crypto';

const MAX_REQUEST_BYTES = 256 * 1024;
const TIMEOUT_MS = 52_000;

function env(name) {
  return globalThis.Netlify?.env?.get(name) ?? process.env[name];
}

function secretMatches(presented, expected) {
  if (!presented || !expected || typeof presented !== 'string' || typeof expected !== 'string') return false;
  const a = Buffer.from(presented);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

function configuredUpstream() {
  const value = env('NASS_BACKEND_URL');
  if (!value) return null;
  let parsed;
  try { parsed = new URL(value); } catch { return null; }
  if (parsed.protocol !== 'https:' || !parsed.hostname || parsed.username || parsed.password ||
      parsed.search || parsed.hash || !parsed.pathname.endsWith('/mcp')) return null;
  if (parsed.hostname === 'localhost' || parsed.hostname.endsWith('.localhost') ||
      /^(127\.|10\.|192\.168\.|169\.254\.|0\.|172\.(1[6-9]|2\d|3[0-1])\.)/.test(parsed.hostname) ||
      parsed.hostname === '[::1]') return null;
  return parsed.href;
}

const text = (s, status, headers={}) => new Response(s, {
  status, headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store', ...headers },
});

export default async function handler(request) {
  if (request.method !== 'POST') return text('Method not allowed', 405, { Allow: 'POST' });

  const expected = env('NASS_MCP_BEARER_TOKEN');
  const match = request.headers.get('authorization')?.match(/^Bearer\s+(\S+)$/i);
  if (!secretMatches(match?.[1], expected)) return text('Unauthorized', 401);

  const backend = configuredUpstream();
  const backendToken = env('NASS_BACKEND_TOKEN');
  if (!backend || !backendToken) return text('Upstream unavailable: backend URL or backend token not configured', 503);

  const accept = request.headers.get('accept') || '';
  if (!(accept.includes('application/json') && accept.includes('text/event-stream'))) {
    return text('MCP requires Accept: application/json, text/event-stream', 406);
  }
  const type = request.headers.get('content-type') || '';
  if (!type.toLowerCase().includes('application/json')) return text('JSON requests only', 415);
  const declared = request.headers.get('content-length');
  if (declared && Number(declared) > MAX_REQUEST_BYTES) return text('Request too large', 413);

  let payload;
  try { payload = await request.arrayBuffer(); } catch { return text('Invalid request body', 400); }
  if (payload.byteLength > MAX_REQUEST_BYTES) return text('Request too large', 413);
  try { JSON.parse(new TextDecoder().decode(payload)); } catch { return text('Invalid JSON', 400); }

  const headers = new Headers({
    Authorization: `Bearer ${backendToken}`,
    'Content-Type': 'application/json',
    Accept: accept,
  });
  for (const name of ['mcp-protocol-version', 'mcp-session-id']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  try {
    const response = await fetch(backend, {
      method: 'POST', headers, body: payload, redirect: 'error',
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const responseHeaders = new Headers({ 'Cache-Control': 'no-store' });
    for (const key of ['content-type', 'mcp-session-id', 'mcp-protocol-version']) {
      const value = response.headers.get(key);
      if (value) responseHeaders.set(key, value);
    }
    return new Response(response.body, { status: response.status, headers: responseHeaders });
  } catch (error) {
    // Avoid leaking upstream URL, token or stack traces to MCP clients.
    return text(error?.name === 'TimeoutError' ? 'Upstream timed out' : 'Upstream connection failed', 502);
  }
}

export const config = {
  path: '/mcp',
  rateLimit: { windowSize: 60, windowLimit: 60, aggregateBy: ['ip', 'domain'] },
};
