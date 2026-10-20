import test from 'node:test';
import assert from 'node:assert/strict';
import handler from '../netlify/functions/mcp.mjs';

const url='https://nass-mcp-remote.netlify.app/mcp';
const validHeaders={'authorization':'Bearer test-pass-abc','content-type':'application/json','accept':'application/json, text/event-stream'};
const req=(headers=validHeaders, method='POST', body='{"jsonrpc":"2.0","method":"ping","id":1}') =>
  new Request(url,{method,headers,...(method!=='POST'?{}:{body})});
function setup() {
  process.env.NASS_MCP_BEARER_TOKEN='test-pass-abc';
  process.env.NASS_BACKEND_URL='https://backend.example.org/mcp';
  process.env.NASS_BACKEND_TOKEN='backend-secret';
}
setup();

test('Missing token fails closed', async()=> {
  assert.equal((await handler(req({'content-type':'application/json','accept':'application/json, text/event-stream'}))).status,401);
});
test('Bad token fails closed', async()=> {
  assert.equal((await handler(req({...validHeaders, authorization:'Bearer other'}))).status,401);
});
test('Unconfigured backend fails closed', async()=> {
  const v=process.env.NASS_BACKEND_URL; delete process.env.NASS_BACKEND_URL;
  try { assert.equal((await handler(req())).status,503); }
  finally {process.env.NASS_BACKEND_URL=v;}
});
test('Private address upstream refused', async()=> {
  const v=process.env.NASS_BACKEND_URL;process.env.NASS_BACKEND_URL='https://127.0.0.1/mcp';
  try {assert.equal((await handler(req())).status,503);}finally{process.env.NASS_BACKEND_URL=v;}
});
test('Non MCP Accept returns 406', async()=> {
  assert.equal((await handler(req({...validHeaders, accept:'application/json'}))).status,406);
});
test('Non JSON rejects', async()=> {
  assert.equal((await handler(req({...validHeaders, 'content-type':'text/plain'}))).status,415);
});
test('Oversize returns 413',async()=> {
  assert.equal((await handler(req(validHeaders,'POST',JSON.stringify({large:'x'.repeat(262144)})))).status,413);
});
test('GET refuses SSE stream', async()=> {
  assert.equal((await handler(req({},'GET'))).status,405);
});
test('Valid call forwards only necessary headers and preserves MCP response', async()=> {
  const old=globalThis.fetch;let called=null;
  globalThis.fetch=async (dest, options)=> {
    called={dest,options};return new Response('{"jsonrpc":"2.0","result":{"ok":true},"id":1}',{headers:{'content-type':'application/json','mcp-session-id':'xyz','x-backend-secret':'do-not-forward'}});
  };
  try {
    const response=await handler(req({...validHeaders,'mcp-protocol-version':'2025-06-18'}));
    assert.equal(response.status,200);
    assert.deepEqual((await response.json()).result,{ok:true});
    assert.equal(called.dest,'https://backend.example.org/mcp');
    assert.equal(called.options.headers.get('authorization'),'Bearer backend-secret');
    assert.equal(called.options.headers.get('mcp-protocol-version'),'2025-06-18');
    assert.equal(response.headers.get('mcp-session-id'),'xyz');
    assert.equal(response.headers.get('x-backend-secret'),null);
  } finally {globalThis.fetch=old;}
});
test('Network failure returns 502 without leaking secrets',async()=> {
 const old=globalThis.fetch;globalThis.fetch=async()=>{throw new Error('secret backend-secret')};
 try {const r=await handler(req());assert.equal(r.status,502);assert.doesNotMatch(await r.text(),/backend-secret/);}finally{globalThis.fetch=old;}
});
