export default async function handler() {
  const backendUrl = globalThis.Netlify?.env?.get('NASS_BACKEND_URL') ?? process.env.NASS_BACKEND_URL;
  const backendToken = globalThis.Netlify?.env?.get('NASS_BACKEND_TOKEN') ?? process.env.NASS_BACKEND_TOKEN;
  const gatewayToken = globalThis.Netlify?.env?.get('NASS_MCP_BEARER_TOKEN') ?? process.env.NASS_MCP_BEARER_TOKEN;
  return Response.json({
    name: 'Nass remote gateway', version: '0.3.0',
    gateway: 'running', backendConfigured: !!(backendUrl && backendToken && gatewayToken),
    note: 'This does not prove that the Python ASR backend is running.'
  }, { headers: { 'Cache-Control': 'no-store' }});
}
export const config = { path: '/health', method: 'GET' };
