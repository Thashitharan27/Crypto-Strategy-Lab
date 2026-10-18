import assert from "node:assert/strict";
import {test} from "node:test";
import {build} from "esbuild";
import {resolve} from "node:path";

// Compile the actual unmounted TSX module using Vite's existing esbuild dependency.
// No DOM is mounted and no production endpoint is contacted.
const bundle = await build({
  entryPoints: [resolve("src/GuardedRunControls.tsx")],
  platform: "node", format: "cjs", bundle: true, write: false, logLevel: "silent",
});
const generated = {exports: {}};
new Function("module", "exports", "require", bundle.outputFiles[0].text)(
  generated, generated.exports, await import("node:module").then(m => m.createRequire(import.meta.url)),
);
const api = generated.exports;
const TOKEN = "test-only-token";

test("all guarded operations deny before network access", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw new Error("must never call fetch"); };
  const request = {
    exchange: "binance", market: "futures_um", symbol: "BTCUSDT",
    period_start: "2025-01-01T00:00:00Z", period_end: "2025-01-02T00:00:00Z",
    strategy_timeframe: "4h", intrabar_timeframe: "1m",
  };
  try {
    for (const invoke of [
      () => api.saveGuardedConfig(false, TOKEN, "../bad", {}),
      () => api.submitGuardedRun(false, TOKEN, "../bad", request, {}),
      () => api.guardedStatus(false, TOKEN, "../bad"),
      () => api.guardedProgress(false, TOKEN, "../bad"),
      () => api.guardedCancel(false, TOKEN, "../bad"),
    ]) {
      assert.throws(invoke, /disabled/);
    }
    assert.equal(calls, 0);
  } finally { globalThis.fetch = original; }
});

test("guarded operations call only existing authenticated local endpoints", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({url, init});
    return {ok: true, json: async () => ({request_id: "run-1", status: "COMPLETED", phase: "loading", config_id: "native"})};
  };
  const request = {
    exchange: "binance", market: "futures_um", symbol: "BTCUSDT",
    period_start: "2025-01-01T00:00:00Z", period_end: "2025-01-02T00:00:00Z",
    strategy_timeframe: "4h", intrabar_timeframe: "1m",
  };
  try {
    await api.saveGuardedConfig(true, TOKEN, "native", {config_version: 3});
    await api.submitGuardedRun(true, TOKEN, "run-1", request, {config_version: 3});
    await api.guardedStatus(true, TOKEN, "run-1");
    await api.guardedProgress(true, TOKEN, "run-1");
    await api.guardedCancel(true, TOKEN, "run-1");
    assert.deepEqual(calls.map(c => [c.init.method, c.url]), [
      ["PUT", "/api/v1/guarded/configs/native"],
      ["POST", "/api/v1/guarded/jobs"],
      ["GET", "/api/v1/guarded/jobs/run-1"],
      ["GET", "/api/v1/guarded/jobs/run-1/progress"],
      ["POST", "/api/v1/guarded/jobs/run-1/cancel"],
    ]);
    for (const {init} of calls) {
      assert.equal(init.headers.Authorization, "Bearer " + TOKEN);
      assert.equal(init.credentials, "omit");
      assert.equal(init.redirect, "error");
      assert.equal(init.cache, "no-store");
    }
    assert.deepEqual(JSON.parse(calls[1].init.body), {
      request_id: "run-1", request, config: {config_version: 3},
    });
  } finally { globalThis.fetch = original; }
});

test("malformed IDs, tokens and failed HTTP responses do not leak private diagnostics", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return {ok: false, status: 409, text: async () => "/private/secret/native/path"};
  };
  try {
    assert.throws(() => api.guardedStatus(true, TOKEN, "../escape"), /Invalid identifier/);
    assert.throws(() => api.guardedStatus(true, "bad\rheader", "run-1"), /Invalid session token/);
    assert.equal(calls, 0);
    await assert.rejects(api.guardedStatus(true, TOKEN, "run-1"), error => {
      assert.match(error.message, /HTTP 409/);
      assert.doesNotMatch(error.message, /private|secret|native\/path/);
      return true;
    });
    assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});
