/** Deterministic coverage for shared JoinPeerTube registry parsing. */

import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";
import { fetchInstanceRegistryHosts, parseInstanceRegistryHosts } from "../../src/instance-registry.js";

test("registry parser preserves order, normalizes hosts, and removes duplicates", () => {
  assert.deepEqual(
    parseInstanceRegistryHosts({
      data: [
        { host: "HTTPS://Example.org/" },
        "second.example",
        { host: "example.org" },
        { nope: "ignored" },
        ""
      ]
    }),
    ["example.org", "second.example"]
  );
});

test("registry parser accepts top-level arrays and rejects unusable payloads", () => {
  assert.deepEqual(parseInstanceRegistryHosts(["one.example", 123]), ["one.example", "123"]);
  assert.throws(() => parseInstanceRegistryHosts({ data: [{ nope: true }] }), /no hosts/);
  assert.throws(() => parseInstanceRegistryHosts({}), /Unexpected whitelist JSON shape/);
});


test("registry fetch preserves retry behavior before parsing normalized hosts", async () => {
  let requests = 0;
  const server = http.createServer((_request, response) => {
    requests += 1;
    if (requests === 1) {
      response.writeHead(500, { "content-type": "application/json" }).end("{}");
      return;
    }
    response.writeHead(200, { "content-type": "application/json" }).end(
      JSON.stringify({ data: [{ host: "Retry.Example" }] })
    );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    const hosts = await fetchInstanceRegistryHosts(
      `http://127.0.0.1:${address.port}/instances`,
      { timeoutMs: 1000, maxRetries: 1 }
    );
    assert.deepEqual(hosts, ["retry.example"]);
    assert.equal(requests, 2);
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => error ? reject(error) : resolve())
    );
  }
});

test("registry fetch does not retry a permanent HTTP client error", async () => {
  let requests = 0;
  const server = http.createServer((_request, response) => {
    requests += 1;
    response.writeHead(406, { "content-type": "application/json" }).end("{}");
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await assert.rejects(
      fetchInstanceRegistryHosts(
        `http://127.0.0.1:${address.port}/instances`,
        { timeoutMs: 1000, maxRetries: 5 }
      ),
      /HTTP 406/
    );
    assert.equal(requests, 1);
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => error ? reject(error) : resolve())
    );
  }
});

test("registry fetch bounds rate-limit retries by maxRetries", async () => {
  let requests = 0;
  const server = http.createServer((_request, response) => {
    requests += 1;
    response.writeHead(429, {
      "content-type": "application/json",
      "retry-after": "0"
    }).end("{}");
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await assert.rejects(
      fetchInstanceRegistryHosts(
        `http://127.0.0.1:${address.port}/instances`,
        { timeoutMs: 1000, maxRetries: 1 }
      ),
      /HTTP 429/
    );
    assert.equal(requests, 2);
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => error ? reject(error) : resolve())
    );
  }
});

for (const payload of [[], {data: []}]) {
  test(`structurally empty registry requires explicit permission: ${JSON.stringify(payload)}`, () => {
    assert.throws(() => parseInstanceRegistryHosts(payload), /no hosts/);
    assert.deepEqual(parseInstanceRegistryHosts(payload, true), []);
  });
}
for (const payload of [{}, {data: {}}, [null], {data: [{nope: true}]}]) {
  test(`empty permission does not admit corrupt registry: ${JSON.stringify(payload)}`, () => {
    assert.throws(() => parseInstanceRegistryHosts(payload, true));
  });
}

for(const payload of [[],{data:[]},[null],{data:[{nope:true}]},{},{data:{}},'malformed']) {
  test(`fetch preserves structural opt-in boundary: ${JSON.stringify(payload)}`,async()=>{
    const old=globalThis.fetch;
    globalThis.fetch=async()=>new Response(payload==='malformed'?'{bad':JSON.stringify(payload));
    try {
      await assert.rejects(fetchInstanceRegistryHosts('https://registry.org',{timeoutMs:50,maxRetries:0}));
      const promise=fetchInstanceRegistryHosts('https://registry.org',{timeoutMs:50,maxRetries:0,allowEmptyList:true});
      if(Array.isArray(payload) && payload.length===0 || typeof payload==='object' && payload && 'data' in payload && Array.isArray(payload.data) && payload.data.length===0)
        assert.deepEqual(await promise,[]);
      else await assert.rejects(promise);
    }finally{globalThis.fetch=old;}
  });
}

test('local HTTP registry matrix forwards only structurally empty opt-in and never hides fetch errors',async()=>{
  const payloads=[[],{data:[]},[null],{data:[{nope:true}]},{},{data:{}},'malformed','http-error'];
  const server=http.createServer((request,response)=>{
    const payload=payloads[Number(request.url!.slice(1))];
    response.writeHead(payload==='http-error'?406:200,{'content-type':'application/json'}).end(payload==='malformed'?'{bad':JSON.stringify(payload));
  });
  await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));
  const address=server.address();assert.ok(address && typeof address==='object');
  try {for(let i=0;i<payloads.length;i++) {
    const url=`http://127.0.0.1:${address.port}/${i}`;
    await assert.rejects(fetchInstanceRegistryHosts(url,{timeoutMs:1000,maxRetries:0}));
    const request=fetchInstanceRegistryHosts(url,{timeoutMs:1000,maxRetries:0,allowEmptyList:true});
    if(i<2)assert.deepEqual(await request,[]);else await assert.rejects(request);
  }}finally{await new Promise<void>((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}
});
