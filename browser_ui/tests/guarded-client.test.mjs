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

test("ordinary client can authenticate the release capability read", async () => {
  const compiled = await build({entryPoints: [resolve("src/api.ts")], platform: "node",
    format: "cjs", bundle: true, write: false, logLevel: "silent"});
  const module = {exports: {}};
  new Function("module", "exports", compiled.outputFiles[0].text)(module, module.exports);
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (path, options) => {
    calls.push({path, options});
    return {ok: true, json: async () => ({execution: false, configuration_editing: false})};
  };
  try {
    assert.deepEqual(await module.exports.getReadOnly("/api/v1/release/capabilities", TOKEN),
      {execution: false, configuration_editing: false});
    assert.equal(calls.length, 1);
    assert.equal(calls[0].options.method, "GET");
    assert.equal(calls[0].options.headers.Authorization, `Bearer ${TOKEN}`);
    await assert.rejects(module.exports.getReadOnly("/api/v1/release/activate", TOKEN), /Unsupported API path/);
    assert.equal(calls.length, 1);
  } finally { globalThis.fetch = original; }
});

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

test("operator switch clears native config and ignores previous-session loaded config", async () => {
  const original = globalThis.fetch;
  let complete;
  globalThis.fetch = async () => new Promise(resolve => {complete = resolve;});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-config-id", "original-config");
    ui.change("guard-config-json", '{"config_version":3,"owner":"first"}', "textarea");
    ui.click("Load saved native configuration");
    ui.rerender({enabled: true, token: "second-operator"});
    complete({ok: true, json: async () => ({config: {owner: "obsolete"}})});
    await settleHandlers();
    ui.render();
    assert.equal(ui.find("input", "guard-config-id").props.value, "");
    assert.equal(ui.find("textarea", "guard-config-json").props.value, "{}");
    assert.ok(!JSON.stringify(ui.find("section", undefined).props.children).includes("obsolete"));
  } finally {globalThis.fetch = original;}
});

test("operator switch resets guarded request and saved-run IDs", async () => {
  const ui = guardedEventHarness();
  ui.change("guard-job-id", "previous-job");
  ui.change("guard-saved-run-folder", "previous-native-folder");
  ui.change("guard-config-id", "previous-config");
  ui.change("guard-config-json", '{"config_version":3,"owner":"old"}', "textarea");
  ui.rerender({enabled: true, token: "next-operator-token"});
  // The test harness commits effect state on the next render.
  ui.render();
  assert.equal(ui.find("input", "guard-job-id").props.value, "");
  assert.equal(ui.find("input", "guard-saved-run-folder").props.value, "");
  assert.equal(ui.find("input", "guard-config-id").props.value, "");
  assert.equal(ui.find("textarea", "guard-config-json").props.value, "{}");
});

test("manual guarded config edit wins over a delayed load for the same ID", async () => {
  const original = globalThis.fetch;
  let complete;
  globalThis.fetch = async () => new Promise(resolve => {complete = resolve;});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-config-id", "same-config");
    ui.click("Load saved native configuration");
    ui.change("guard-config-json", '{"config_version":3,"owner":"edited"}', "textarea");
    complete({ok: true, json: async () => ({config: {owner: "obsolete"}})});
    await settleHandlers();
    ui.render();
    assert.equal(ui.find("textarea", "guard-config-json").props.value,
      '{"config_version":3,"owner":"edited"}');
  } finally {globalThis.fetch = original;}
});

test("configuration actions preserve completed job state and terminal progress lockout", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => ({ok: true, json: async () => {
    if (url.endsWith("/guarded/jobs/job-A")) return {request_id: "job-A", status: "COMPLETED"};
    if (url.endsWith("/configs/safe") && options?.method === "GET") return {config: {config_version: 3}};
    return {config_id: "safe", status: "SAVED"};
  }});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "job-A");
    ui.click("Refresh status");
    await settleHandlers();
    ui.render();
    assert.equal(ui.find("button", "Refresh progress").props.disabled, true);
    ui.change("guard-config-id", "safe");
    ui.click("Load saved native configuration");
    await settleHandlers();
    ui.render();
    assert.equal(ui.find("button", "Refresh progress").props.disabled, true);
    ui.click("Save native configuration");
    await settleHandlers();
    ui.render();
    assert.equal(ui.find("button", "Refresh progress").props.disabled, true);
    const output = JSON.stringify(ui.find("section", undefined).props.children);
    assert.ok(output.includes("Native worker completed"));
    assert.ok(output.includes("Configuration safe: SAVED"));
  } finally {globalThis.fetch = original;}
});

test("configuration actions preserve recovery-unverified job lockout", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url) => ({ok: true, json: async () => {
    if (url.endsWith("/guarded/jobs/interrupted")) return {request_id: "interrupted", status: "RECOVERY_UNVERIFIED"};
    return {config_id: "safe", status: "SAVED"};
  }});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "interrupted");
    ui.click("Refresh status");
    await settleHandlers();
    ui.change("guard-config-id", "safe");
    ui.change("guard-config-json", '{"config_version":3}', "textarea");
    ui.click("Save native configuration");
    await settleHandlers();
    ui.render();
    for (const name of ["Refresh progress", "Request cancellation", "Submit native research run"]) {
      assert.equal(ui.find("button", name).props.disabled, true, name);
    }
    const output = JSON.stringify(ui.find("section", undefined).props.children);
    assert.ok(output.includes("Recovery unverified"));
    assert.ok(output.includes("Configuration safe: SAVED"));
  } finally {globalThis.fetch = original;}
});

test("editing a saved config clears prior persistence acknowledgement without changing job status", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url) => ({ok: true, json: async () =>
    url.endsWith("/guarded/jobs/job-A")
      ? {request_id: "job-A", status: "COMPLETED"}
      : {config_id: "safe", status: "SAVED"},
  });
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "job-A");
    ui.click("Refresh status");
    await settleHandlers();
    ui.change("guard-config-id", "safe");
    ui.change("guard-config-json", '{"config_version":3}', "textarea");
    ui.click("Save native configuration");
    await settleHandlers();
    ui.render();
    let output = JSON.stringify(ui.find("section", undefined).props.children);
    assert.ok(output.includes("Configuration safe: SAVED"));
    assert.equal(ui.find("button", "Refresh progress").props.disabled, true);
    ui.change("guard-config-json", '{"config_version":3,"edited":true}', "textarea");
    ui.render();
    output = JSON.stringify(ui.find("section", undefined).props.children);
    assert.ok(!output.includes("Configuration safe: SAVED"));
    assert.ok(output.includes("Native worker completed"));
    assert.equal(ui.find("button", "Refresh progress").props.disabled, true);
  } finally {globalThis.fetch = original;}
});

test("guarded config save rejects mismatched or unbounded acknowledgements", async () => {
  const original = globalThis.fetch;
  const responses = [
    {config_id: "different", status: "SAVED"},
    {config_id: "safe", status: "/private/native/path"},
    {config_id: 123, status: "SAVED"},
    null,
  ];
  let index = 0;
  globalThis.fetch = async () => ({ok: true, json: async () => responses[index++]});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-config-id", "safe");
    ui.change("guard-config-json", '{"config_version":3}', "textarea");
    for (const _ of responses) {
      ui.click("Save native configuration");
      await settleHandlers();
      ui.render();
      const rendered = JSON.stringify(ui.find("section", undefined).props.children);
      assert.ok(rendered.includes("Guarded operation unavailable or rejected"));
      assert.ok(!rendered.includes("/private/native/path"));
      assert.ok(!rendered.includes("Configuration different"));
      assert.ok(!rendered.includes("Configuration safe: SAVED"));
    }
  } finally {globalThis.fetch = original;}
});

test("guarded config save accepts only matching native success acknowledgement", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ok: true, json: async () => ({config_id: "safe", status: "SAVED"})});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-config-id", "safe");
    ui.change("guard-config-json", '{"config_version":3}', "textarea");
    ui.click("Save native configuration");
    await settleHandlers();
    ui.render();
    const rendered = JSON.stringify(ui.find("section", undefined).props.children);
    assert.ok(rendered.includes("Configuration safe: SAVED"));
  } finally {globalThis.fetch = original;}
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


test("late rejected operations cannot mark a newly selected run or config as failed", async () => {
  for (const [field, action, nextId] of [
    ["guard-job-id", "Refresh status", "next-job"],
    ["guard-job-id", "Refresh progress", "next-job"],
    ["guard-job-id", "Request cancellation", "next-job"],
    ["guard-job-id", "Submit native research run", "next-job"],
    ["guard-config-id", "Load saved native configuration", "next-config"],
    ["guard-config-id", "Save native configuration", "next-config"],
  ]) {
    const original = globalThis.fetch;
    let rejectRequest;
    globalThis.fetch = async () => new Promise((_resolve, reject) => {rejectRequest = reject;});
    try {
      const ui = guardedEventHarness();
      ui.change(field, "original");
      ui.change("guard-config-json", '{"config_version":3}', "textarea");
      ui.click(action);
      assert.equal(typeof rejectRequest, "function", action);
      ui.change(field, nextId);
      rejectRequest(new Error("/private/sensitive/native-file"));
      await settleHandlers();
      ui.render();
      const messages = [];
      const collect = node => {
        if (!node || typeof node !== "object") return;
        if (node.props?.role === "alert") messages.push(String(node.props.children));
        for (const child of [].concat(node.props?.children ?? [])) collect(child);
      };
      collect(ui.find("section", undefined));
      assert.deepEqual(messages, [], action + " polluted new selection with stale error");
    } finally {globalThis.fetch = original;}
  }
});


test("guarded recovery state does not imply completion or allow cancellation", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    return {ok: true, json: async () => ({
      request_id: "interrupted", status: "RECOVERY_UNVERIFIED",
    })};
  };
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "interrupted");
    ui.click("Refresh status");
    await settleHandlers();
    ui.render();
    assert.equal(ui.find("button", "Request cancellation").props.disabled, true);
    assert.equal(ui.find("button", "Refresh progress").props.disabled, true);
    assert.equal(ui.find("button", "Submit native research run").props.disabled, true);
    const children = ui.find("section", undefined).props.children;
    assert.ok(JSON.stringify(children).includes("Recovery unverified"));
    assert.ok(JSON.stringify(children).includes("Do not resubmit or assume completion"));
    assert.equal(calls.length, 1);
    ui.change("guard-job-id", "another");
    assert.equal(ui.find("button", "Request cancellation").props.disabled, false);
    assert.equal(ui.find("button", "Refresh progress").props.disabled, false);
    assert.equal(ui.find("button", "Submit native research run").props.disabled, false);
  } finally {globalThis.fetch = original;}
});

test("guarded native statuses reject unknown states and mismatched identities", async () => {
  const original = globalThis.fetch;
  const cases = [
    {request_id: "different", status: "COMPLETED"},
    {request_id: "chosen", status: "PRIVATE_/home/user/data"},
  ];
  let index = 0;
  globalThis.fetch = async () => ({ok: true, json: async () => cases[index++]});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "chosen");
    for (const _ of cases) {
      ui.click("Refresh status");
      await settleHandlers();
      ui.render();
      const serialized = JSON.stringify(ui.find("section", undefined).props.children);
      assert.ok(serialized.includes("Guarded operation unavailable or rejected"));
      assert.ok(!serialized.includes("/home/user/data"));
    }
  } finally {globalThis.fetch = original;}
});

test("guarded progress rejects native diagnostics and malformed phases", async () => {
  const original = globalThis.fetch;
  const phases = [
    {phase: "/private/output/native-run"},
    {phase: "SECRET_TOKEN=private"},
    {phase: "x".repeat(100)},
    {phase: 123},
    null,
  ];
  let next = 0;
  globalThis.fetch = async () => ({ok: true, json: async () => phases[next++]});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "safe-job");
    for (const _ of phases) {
      ui.click("Refresh progress");
      await settleHandlers();
      ui.render();
      const rendered = JSON.stringify(ui.find("section", undefined).props.children);
      assert.ok(rendered.includes("Guarded operation unavailable or rejected"));
      assert.ok(!rendered.includes("/private/output"));
      assert.ok(!rendered.includes("SECRET_TOKEN"));
      assert.ok(!rendered.includes("Latest native stage:"));
    }
  } finally {globalThis.fetch = original;}
});

test("guarded progress accepts bounded stages and missing phase only", async () => {
  const original = globalThis.fetch;
  const responses = [{phase: "loading_1"}, {}];
  let index = 0;
  globalThis.fetch = async () => ({ok: true, json: async () => responses[index++]});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "safe-job");
    ui.click("Refresh progress");
    await settleHandlers();
    ui.render();
    assert.ok(JSON.stringify(ui.find("section", undefined).props.children).includes("loading_1"));
    ui.click("Refresh progress");
    await settleHandlers();
    ui.render();
    assert.ok(JSON.stringify(ui.find("section", undefined).props.children).includes("No stage available"));
  } finally {globalThis.fetch = original;}
});

test("terminal guarded job outcomes clear stale active progress stages", async () => {
  const original = globalThis.fetch;
  try {
    for (const [action, terminal] of [
      ["Refresh status", "COMPLETED"],
      ["Refresh status", "FAILED"],
      ["Request cancellation", "CANCELLED"],
      ["Refresh status", "RECOVERY_UNVERIFIED"],
    ]) {
      globalThis.fetch = async (path) => ({ok: true, json: async () =>
        path.endsWith("/progress")
          ? {phase: "preparing"}
          : {request_id: "job-A", status: terminal},
      });
      const ui = guardedEventHarness();
      ui.change("guard-job-id", "job-A");
      ui.click("Refresh progress");
      await settleHandlers();
      ui.render();
      assert.ok(JSON.stringify(ui.find("section", undefined).props.children).includes("preparing"));
      ui.click(action);
      await settleHandlers();
      ui.render();
      const displayed = JSON.stringify(ui.find("section", undefined).props.children);
      assert.ok(!displayed.includes("Latest native stage:"), action + " " + terminal);
      assert.equal(ui.find("button", "Refresh progress").props.disabled, true, terminal);
    }
  } finally {globalThis.fetch = original;}
});

test("cancellation unavailable preserves progress while native job may still run", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (path) => ({ok: true, json: async () =>
    path.endsWith("/progress")
      ? {phase: "running"}
      : {request_id: "job-A", status: "CANCELLATION_UNAVAILABLE"},
  });
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "job-A");
    ui.click("Refresh progress");
    await settleHandlers();
    ui.click("Request cancellation");
    await settleHandlers();
    ui.render();
    const displayed = JSON.stringify(ui.find("section", undefined).props.children);
    assert.ok(displayed.includes("Latest native stage:"));
    assert.ok(displayed.includes("running"));
    assert.ok(displayed.includes("Cancellation unavailable"));
    assert.equal(ui.find("button", "Refresh progress").props.disabled, false);
  } finally {globalThis.fetch = original;}
});

test("guarded cancellation unavailable is never displayed as cancelled", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ok: true, json: async () => ({
    request_id: "busy", status: "CANCELLATION_UNAVAILABLE",
  })});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "busy");
    ui.click("Request cancellation");
    await settleHandlers();
    ui.render();
    const serialized = JSON.stringify(ui.find("section", undefined).props.children);
    assert.ok(serialized.includes("Cancellation unavailable"));
    assert.ok(serialized.includes("No cancellation is confirmed"));
  } finally {globalThis.fetch = original;}
});


test("guarded verified saved-run handoff uses explicit folder ID, not request ID", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (path, options) => {
    calls.push([path, options]);
    return {ok: true, json: async () => ({
      manifest: {run_id: "native-output-42", run_status: "COMPLETED"},
      summary: {total_trades: 3},
    })};
  };
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "request-42");
    ui.change("guard-saved-run-folder", "folder-42");
    ui.click("Inspect verified saved run");
    await settleHandlers();
    ui.render();
    assert.deepEqual(calls.map(([url, init]) => [url, init.method]), [
      ["/api/v1/runs/folder-42", "GET"],
    ]);
    const displayed = JSON.stringify(ui.find("section", undefined).props.children);
    assert.ok(displayed.includes("native-output-42"));
    assert.ok(displayed.includes("folder-42"));
    assert.ok(!calls[0][0].includes("request-42"));
  } finally { globalThis.fetch = original; }
});

test("saved-run handoff hides old results after folder or session changes", async () => {
  for (const switchContext of ["folder", "session"]) {
    const original = globalThis.fetch;
    let complete;
    globalThis.fetch = async () => new Promise(resolve => {complete = resolve;});
    try {
      const ui = guardedEventHarness();
      ui.change("guard-saved-run-folder", "first-folder");
      ui.click("Inspect verified saved run");
      if (switchContext === "folder") ui.change("guard-saved-run-folder", "second-folder");
      else ui.rerender({enabled: true, token: "changed-session-token"});
      complete({ok: true, json: async () => ({
        manifest: {run_id: "obsolete-run", run_status: "COMPLETED"}, summary: {},
      })});
      await settleHandlers();
      ui.render();
      const displayed = JSON.stringify(ui.find("section", undefined).props.children);
      assert.ok(!displayed.includes("obsolete-run"), switchContext);
    } finally {globalThis.fetch = original;}
  }
});

test("latest repeat saved-run inspection wins when responses resolve out of order", async () => {
  const original = globalThis.fetch;
  const resolves = [];
  globalThis.fetch = async () => new Promise(resolve => resolves.push(resolve));
  try {
    const ui = guardedEventHarness();
    ui.change("guard-saved-run-folder", "stable-folder");
    ui.click("Inspect verified saved run");
    ui.click("Inspect verified saved run");
    assert.equal(resolves.length, 2);
    resolves[1]({ok: true, json: async () => ({
      manifest: {run_id: "newer-run", run_status: "COMPLETED"}, summary: {},
    })});
    await settleHandlers();
    ui.render();
    assert.ok(JSON.stringify(ui.find("section", undefined).props.children).includes("newer-run"));
    resolves[0]({ok: true, json: async () => ({
      manifest: {run_id: "obsolete-run", run_status: "COMPLETED"}, summary: {},
    })});
    await settleHandlers();
    ui.render();
    const displayed = JSON.stringify(ui.find("section", undefined).props.children);
    assert.ok(displayed.includes("newer-run"));
    assert.ok(!displayed.includes("obsolete-run"));
  } finally {globalThis.fetch = original;}
});

test("late failed saved-run inspection cannot mark newer successful inspection as failed", async () => {
  const original = globalThis.fetch;
  const settles = [];
  globalThis.fetch = () => new Promise((resolve, reject) => settles.push({resolve, reject}));
  try {
    const ui = guardedEventHarness();
    ui.change("guard-saved-run-folder", "stable-folder");
    ui.click("Inspect verified saved run");
    ui.click("Inspect verified saved run");
    settles[1].resolve({ok: true, json: async () => ({
      manifest: {run_id: "newer-run", run_status: "COMPLETED"}, summary: {},
    })});
    await settleHandlers();
    settles[0].reject(new Error("stale read"));
    await settleHandlers();
    ui.render();
    const displayed = JSON.stringify(ui.find("section", undefined).props.children);
    assert.ok(displayed.includes("newer-run"));
    assert.ok(!displayed.includes("Saved run not available or verification rejected"));
  } finally {globalThis.fetch = original;}
});

test("saved-run handoff rejects malformed IDs and unverified or invalid outputs", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  const responses = [{}, {manifest: {run_id: "native"}, summary: null},
    {manifest: {run_id: 42}, summary: {}}, {manifest: {run_id: "native", run_status: "COMPLETED"}, summary: {}}];
  globalThis.fetch = async () => {
    calls++;
    return {ok: true, json: async () => responses[calls - 1]};
  };
  try {
    await assert.rejects(api.inspectVerifiedSavedRun(false, TOKEN, "valid"), /disabled/);
    await assert.rejects(api.inspectVerifiedSavedRun(true, TOKEN, "../unsafe"), /Invalid identifier/);
    assert.equal(calls, 0);
    for (let i = 0; i < 3; i++) {
      await assert.rejects(api.inspectVerifiedSavedRun(true, TOKEN, "folder"), /Invalid verified saved-run response/);
    }
    assert.deepEqual(await api.inspectVerifiedSavedRun(true, TOKEN, "folder"), {
      folderId: "folder", nativeRunId: "native", runStatus: "COMPLETED",
    });
  } finally {globalThis.fetch = original;}
});


test("guarded saved-run inspection never accepts incomplete native manifests", async () => {
  const original = globalThis.fetch;
  const responses = ["FAILED", "RUNNING", "RECOVERY_UNVERIFIED", undefined, null].map(
    status => ({manifest: {run_id: "native-1", run_status: status}, summary: {}}),
  );
  let index = 0;
  globalThis.fetch = async () => ({ok: true, json: async () => responses[index++]});
  try {
    for (const _ of responses) {
      await assert.rejects(api.inspectVerifiedSavedRun(true, TOKEN, "native-folder"),
        /Invalid verified saved-run response/);
    }
  } finally { globalThis.fetch = original; }
});

test("saved-run handoff rejects unsafe native manifest identity and status strings", async () => {
  const original = globalThis.fetch;
  const responses = [
    {manifest: {run_id: "/private/native/output", run_status: "COMPLETED"}, summary: {}},
    {manifest: {run_id: "valid", run_status: "/private/secret"}, summary: {}},
    {manifest: {run_id: "valid", run_status: "x".repeat(101)}, summary: {}},
    {manifest: {run_id: "valid", run_status: 123}, summary: {}},
    {manifest: {run_id: "a".repeat(101), run_status: "COMPLETED"}, summary: {}},
  ];
  let index = 0;
  globalThis.fetch = async () => ({ok: true, json: async () => responses[index++]});
  try {
    for (const _ of responses) {
      await assert.rejects(api.inspectVerifiedSavedRun(true, TOKEN, "approved-folder"),
        /Invalid verified saved-run response/);
    }
  } finally {globalThis.fetch = original;}
});

test("native verified output folder is offered only for completed matching jobs", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (path) => ({ok: true, json: async () => ({
    request_id: "request-A", status: "COMPLETED",
    verified_run_folder_id: "native-folder-42",
  })});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "request-A");
    ui.click("Refresh status");
    await settleHandlers();
    ui.render();
    assert.equal(ui.find("button", "Select verified native output folder").props.disabled, undefined);
    ui.click("Select verified native output folder");
    assert.equal(ui.find("input", "guard-saved-run-folder").props.value, "native-folder-42");
    ui.change("guard-job-id", "request-B");
    assert.throws(() => ui.find("button", "Select verified native output folder"), /Control not found/);
  } finally {globalThis.fetch = original;}
});

test("unverified outputs are never offered as native verified folder links", async () => {
  const original = globalThis.fetch;
  const cases = [
    {status: "COMPLETED", verified_run_folder_id: "../outside"},
    {status: "COMPLETED", verified_run_folder_id: "bad.name"},
    {status: "RECOVERY_UNVERIFIED", verified_run_folder_id: "valid-but-unverified"},
    {status: "RUNNING", verified_run_folder_id: "claimed-too-early"},
  ];
  let i = 0;
  globalThis.fetch = async () => ({ok: true, json: async () => ({
    request_id: "request-A", ...cases[i++],
  })});
  try {
    const ui = guardedEventHarness();
    ui.change("guard-job-id", "request-A");
    for (const _ of cases) {
      ui.click("Refresh status");
      await settleHandlers();
      ui.render();
      assert.throws(() => ui.find("button", "Select verified native output folder"), /Control not found/);
    }
  } finally {globalThis.fetch = original;}
});


test("production UI mounts guarded controls only from authenticated server capabilities", async () => {
  const {readFileSync} = await import("node:fs");
  const source = readFileSync(resolve("src/main.tsx"), "utf8");
  assert.match(source, /getReadOnly<ReleaseCapabilities>\("\/api\/v1\/release\/capabilities", token\)/);
  assert.match(source, /releaseCapabilities\?\.execution === true/);
  assert.match(source, /releaseCapabilities\?\.configuration_editing === true/);
  assert.match(source, /<GuardedRunControls enabled=\{true\} token=\{token\}\s*\/>/);
  assert.match(source, /setReleaseCapabilities\(null\)/);
  assert.doesNotMatch(source, /import\.meta\.env\.[A-Za-z_]*GUARDED/);
});
