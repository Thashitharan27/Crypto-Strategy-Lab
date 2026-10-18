import assert from "node:assert/strict";
import {test} from "node:test";
import {build} from "esbuild";
import {resolve} from "node:path";

// Compile the actual unmounted TSX module using Vite's existing esbuild dependency.
// No DOM is mounted and no production endpoint is contacted.
const bundle = await build({
  entryPoints: [resolve("src/GuardedRunControls.tsx")],
  platform: "node", format: "cjs", bundle: true, external: ["react", "react-dom"], write: false, logLevel: "silent",
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
    await assert.rejects(api.loadGuardedConfig(false, TOKEN, "../bad"), /disabled/);
    assert.equal(calls, 0);
  } finally { globalThis.fetch = original; }
});

test("guarded operations call only existing authenticated local endpoints", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({url, init});
    return {ok: true, json: async () => ({config: {config_version: 3}, request_id: "run-1", status: "COMPLETED", phase: "loading", config_id: "native"})};
  };
  const request = {
    exchange: "binance", market: "futures_um", symbol: "BTCUSDT",
    period_start: "2025-01-01T00:00:00Z", period_end: "2025-01-02T00:00:00Z",
    strategy_timeframe: "4h", intrabar_timeframe: "1m",
  };
  try {
    const loaded = await api.loadGuardedConfig(true, TOKEN, "native");
    assert.equal(loaded.config_version, 3);
    await api.saveGuardedConfig(true, TOKEN, "native", {config_version: 3});
    await api.submitGuardedRun(true, TOKEN, "run-1", request, {config_version: 3});
    await api.guardedStatus(true, TOKEN, "run-1");
    await api.guardedProgress(true, TOKEN, "run-1");
    await api.guardedCancel(true, TOKEN, "run-1");
    assert.deepEqual(calls.map(c => [c.init.method, c.url]), [
      ["GET", "/api/v1/configs/native"],
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
    assert.deepEqual(JSON.parse(calls[2].init.body), {
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


test("dormant React component renders no controls unless explicitly enabled", async () => {
  const React = await import("react");
  const {renderToStaticMarkup} = await import("react-dom/server");
  const disabled = renderToStaticMarkup(
    React.createElement(api.GuardedRunControls, {token: TOKEN}),
  );
  assert.equal(disabled, "");
  const explicitlyDisabled = renderToStaticMarkup(
    React.createElement(api.GuardedRunControls, {token: TOKEN, enabled: false}),
  );
  assert.equal(explicitlyDisabled, "");
  const enabled = renderToStaticMarkup(
    React.createElement(api.GuardedRunControls, {token: TOKEN, enabled: true}),
  );
  for (const label of [
    "Load saved native configuration", "Save native configuration", "Submit native research run",
    "Refresh status", "Refresh progress", "Request cancellation",
    "Experimental guarded native operations",
  ]) {
    assert.ok(enabled.includes(label), label);
  }
  assert.ok(!enabled.includes(TOKEN), "Session credentials must not appear in markup");
});

test("saved native config loader rejects invalid identifiers and response shapes", async () => {
  const original = globalThis.fetch;
  const cases = [null, [], "text", {config: []}, {config: "raw text"}, {config: null}];
  let index = 0;
  globalThis.fetch = async () => ({
    ok: true, json: async () => cases[index++],
  });
  try {
    await assert.rejects(api.loadGuardedConfig(true, TOKEN, "../escape"), /Invalid identifier/);
    for (let i = 0; i < cases.length; i++) {
      await assert.rejects(api.loadGuardedConfig(true, TOKEN, "safe"), /Invalid native configuration response/);
    }
  } finally { globalThis.fetch = original; }
});


// Exercise the actual event-handler closures and React hook state in the dormant
// TSX component. No DOM, new test framework or production mount is required.
// This deliberately uses React's test-only dispatcher seam, not application code.
const ReactForEvents = await import("react");
const settleHandlers = () => new Promise(resolve => setImmediate(resolve));
function guardedEventHarness(initialProps = {enabled: true, token: TOKEN}) {
  const internals = ReactForEvents.default.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED;
  const hooks = [];
  let props = initialProps;
  let root;
  const dispatch = {
    useState(initial) {
      const index = dispatch.index++;
      if (!(index in hooks)) hooks[index] = typeof initial === "function" ? initial() : initial;
      return [hooks[index], next => { hooks[index] = typeof next === "function" ? next(hooks[index]) : next; }];
    },
    useRef(initial) {
      const index = dispatch.index++;
      if (!(index in hooks)) hooks[index] = {current: initial};
      return hooks[index];
    },
    useEffect(effect, deps) {
      const index = dispatch.index++;
      const previous = hooks[index];
      if (!previous || deps.some((v, i) => v !== previous[i])) {
        hooks[index] = deps;
        dispatch.effects.push(effect);
      }
    },
    index: 0, effects: [],
  };
  function render() {
    dispatch.index = 0;
    dispatch.effects = [];
    const prior = internals.ReactCurrentDispatcher.current;
    internals.ReactCurrentDispatcher.current = dispatch;
    try { root = api.GuardedRunControls(props); }
    finally { internals.ReactCurrentDispatcher.current = prior; }
    for (const effect of dispatch.effects) effect();
    return root;
  }
  function find(tag, idOrText) {
    const stack = [root];
    while (stack.length) {
      const node = stack.pop();
      if (!node || typeof node !== "object") continue;
      if (node.type === tag &&
          (node.props?.id === idOrText || node.props?.children === idOrText)) return node;
      const children = node.props?.children;
      if (Array.isArray(children)) stack.push(...children.slice().reverse());
      else if (children) stack.push(children);
    }
    throw new Error("Control not found: " + tag + " " + idOrText);
  }
  function change(id, value, tag = "input") {
    find(tag, id).props.onChange({target: {value}});
    render();
  }
  function click(text) {
    find("button", text).props.onClick();
    render();
  }
  function rerender(nextProps) { props = nextProps; render(); }
  render();
  return {find, change, click, render, rerender};
}

test("guarded editor click-load, ID switch and edit/save preserve selection ownership", async () => {
  const original = globalThis.fetch;
  const calls = [];
  let resolveLoad;
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    if (options.method === "GET") return new Promise(resolve => { resolveLoad = resolve; });
    return {ok: true, json: async () => ({config_id: "second", status: "SAVED"})};
  };
  try {
    const ui = guardedEventHarness();
    ui.change("guard-config-id", "first");
    ui.click("Load saved native configuration");
    assert.equal(calls.length, 1);
    ui.change("guard-config-id", "second");
    resolveLoad({ok: true, json: async () => ({config: {config_version: 3, symbol: "OLD"}})});
    await settleHandlers();
    ui.render();
    assert.equal(ui.find("textarea", "guard-config-json").props.value, "{}");
    ui.change("guard-config-json", '{"config_version":3,"symbol":"NEW"}', "textarea");
    ui.click("Save native configuration");
    await settleHandlers();
    assert.equal(calls[1][0], "/api/v1/guarded/configs/second");
    assert.deepEqual(JSON.parse(calls[1][1].body), {config_version: 3, symbol: "NEW"});
  } finally { globalThis.fetch = original; }
});

test("guarded UI click-submit and status/progress/cancel use selected request ID", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    return {ok: true, json: async () => ({request_id: "job-A", status: "QUEUED", phase: "VALIDATING"})};
  };
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "job-A");
    ui.change("guard-config-json", '{"config_version":3}', "textarea");
    ui.click("Submit native research run");
    await settleHandlers();
    ui.click("Refresh status");
    await settleHandlers();
    ui.click("Refresh progress");
    await settleHandlers();
    ui.click("Request cancellation");
    await settleHandlers();
    assert.deepEqual(calls.map(([url, options]) => [options.method, url]), [
      ["POST", "/api/v1/guarded/jobs"],
      ["GET", "/api/v1/guarded/jobs/job-A"],
      ["GET", "/api/v1/guarded/jobs/job-A/progress"],
      ["POST", "/api/v1/guarded/jobs/job-A/cancel"],
    ]);
    assert.equal(JSON.parse(calls[0][1].body).request_id, "job-A");
  } finally { globalThis.fetch = original; }
});

test("operator token switch invalidates in-flight guarded status response", async () => {
  const original = globalThis.fetch;
  let resolveRequest;
  globalThis.fetch = async () => new Promise(resolve => {resolveRequest = resolve;});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "job-A");
    ui.click("Refresh status");
    ui.rerender({enabled: true, token: "different-operator-token"});
    resolveRequest({ok: true, json: async () => ({status: "COMPLETED"})});
    await settleHandlers();
    ui.render();
    const statuses = [];
    // The underlying React state must not receive a previous operator's result.
    const collect = node => {
      if (!node || typeof node !== "object") return;
      if (node.props?.role === "status") statuses.push(String(node.props.children));
      for (const child of [].concat(node.props?.children ?? [])) collect(child);
    };
    collect(ui.find("section", undefined));
    assert.ok(!statuses.some(s => s.includes("COMPLETED")));
  } finally { globalThis.fetch = original; }
});


test("switching guarded job IDs rejects late status and progress results", async () => {
  for (const [action, latest, obsolete] of [
    ["Refresh status", "job-B", "DONE_FROM_A"],
    ["Refresh progress", "job-B", "PROGRESS_FROM_A"],
    ["Request cancellation", "job-B", "CANCELLED_A"],
    ["Submit native research run", "job-B", "SUBMITTED_A"],
  ]) {
    const original = globalThis.fetch;
    let finish;
    const calls = [];
    globalThis.fetch = async (url, options) => {
      calls.push([url, options]);
      return new Promise(resolve => {finish = resolve;});
    };
    try {
      const ui = guardedEventHarness();
      ui.change("guard-job-id", "job-A");
      ui.change("guard-config-json", '{"config_version":3}', "textarea");
      ui.click(action);
      assert.equal(calls.length, 1, action);
      ui.change("guard-job-id", latest);
      finish({ok: true, json: async () => ({status: obsolete, phase: obsolete})});
      await settleHandlers();
      ui.render();
      const statuses = [];
      const collect = node => {
        if (!node || typeof node !== "object") return;
        if (node.props?.role === "status") statuses.push(String(node.props.children));
        for (const child of [].concat(node.props?.children ?? [])) collect(child);
      };
      collect(ui.find("section", undefined));
      assert.ok(!statuses.some(v => v.includes(obsolete)), action + " leaked result from old job");
      assert.equal(ui.find("input", "guard-job-id").props.value, latest);
    } finally {globalThis.fetch = original;}
  }
});
