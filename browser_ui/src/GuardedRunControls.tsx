/** Development-only guarded controls. Not mounted in the production read-only App.
 * The server must separately opt in to its guarded router; UI gating is NOT authorization.
 */
import React from "react";
import {getReadOnly} from "./api";

type NativeRequest = {
  exchange: "binance";
  market: "spot" | "futures_um";
  symbol: string;
  period_start: string;
  period_end: string;
  strategy_timeframe: "15m" | "1h" | "4h" | "1d";
  intrabar_timeframe: "1m" | "5m" | "15m";
};
type JobState = {
  request_id: string;
  status: string;
};
const ID = /^[A-Za-z0-9_-]{1,100}$/;

function requireGuardedSession(enabled: boolean, token: string): void {
  if (enabled !== true) throw new Error("Guarded operations are disabled");
  if (!token || token.includes(String.fromCharCode(13)) || token.includes(String.fromCharCode(10))) throw new Error("Invalid session token");
}

function safeId(value: string): string {
  if (!ID.test(value)) throw new Error("Invalid identifier");
  return value;
}

async function guardedRequest<T>(
  enabled: boolean, token: string, method: "GET" | "POST" | "PUT",
  path: string, payload?: unknown,
): Promise<T> {
  // Fail before fetch even when called from another component or script.
  if (enabled !== true) throw new Error("Guarded operations are disabled");
  if (!token || /[\r\n]/.test(token)) throw new Error("Invalid session token");
  const options: RequestInit = {
    method,
    headers: {Authorization: `Bearer ${token}`, ...(payload === undefined ? {} : {"Content-Type": "application/json"})},
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
  };
  if (payload !== undefined) options.body = JSON.stringify(payload);
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`Guarded operation rejected (HTTP ${response.status})`);
  return response.json() as Promise<T>;
}

export async function loadGuardedConfig(enabled: boolean, token: string, id: string): Promise<Record<string, unknown>> {
  requireGuardedSession(enabled, token);
  const response = await getReadOnly<{config: unknown}>(`/api/v1/configs/${safeId(id)}`, token);
  if (!response || typeof response !== "object" || !response.config ||
      typeof response.config !== "object" || Array.isArray(response.config)) {
    throw new Error("Invalid native configuration response");
  }
  return response.config as Record<string, unknown>;
}

export function saveGuardedConfig(enabled: boolean, token: string, id: string, config: Record<string, unknown>) {
  requireGuardedSession(enabled, token);
  return guardedRequest<{config_id: string; status: string}>(
    enabled, token, "PUT", `/api/v1/guarded/configs/${safeId(id)}`, config,
  );
}
export function submitGuardedRun(enabled: boolean, token: string, id: string, request: NativeRequest, config: Record<string, unknown>) {
  requireGuardedSession(enabled, token);
  return guardedRequest<JobState>(enabled, token, "POST", "/api/v1/guarded/jobs", {
    request_id: safeId(id), request, config,
  });
}
export function guardedStatus(enabled: boolean, token: string, id: string) {
  requireGuardedSession(enabled, token);
  return guardedRequest<JobState>(enabled, token, "GET", `/api/v1/guarded/jobs/${safeId(id)}`);
}
export function guardedProgress(enabled: boolean, token: string, id: string) {
  requireGuardedSession(enabled, token);
  return guardedRequest<{phase?: string}>(enabled, token, "GET", `/api/v1/guarded/jobs/${safeId(id)}/progress`);
}
export function guardedCancel(enabled: boolean, token: string, id: string) {
  requireGuardedSession(enabled, token);
  return guardedRequest<JobState>(enabled, token, "POST", `/api/v1/guarded/jobs/${safeId(id)}/cancel`);
}

export function GuardedRunControls({enabled = false, token}: {enabled?: boolean; token: string}) {
  const [configId, setConfigId] = React.useState("");
  const configSelection = React.useRef({id: "", version: 0});
  const [configJson, setConfigJson] = React.useState("{}");
  const [jobId, setJobId] = React.useState("");
  const jobSelection = React.useRef({id: "", version: 0});
  const [symbol, setSymbol] = React.useState("BTCUSDT");
  const [market, setMarket] = React.useState<"spot" | "futures_um">("futures_um");
  const [from, setFrom] = React.useState("2025-01-01T00:00:00Z");
  const [to, setTo] = React.useState("2025-01-02T00:00:00Z");
  const [timeframe, setTimeframe] = React.useState<NativeRequest["strategy_timeframe"]>("4h");
  const [intrabar, setIntrabar] = React.useState<NativeRequest["intrabar_timeframe"]>("1m");
  const [state, setState] = React.useState("");
  const [phase, setPhase] = React.useState("");
  const [error, setError] = React.useState("");
  const busy = React.useRef(false);
  // Keep the latest authorization/session props visible to pending promises.
  const session = React.useRef({enabled, token, version: 0});
  if (session.current.enabled !== enabled || session.current.token !== token) {
    session.current = {enabled, token, version: session.current.version + 1};
  }
  React.useEffect(() => {
    // Clear information from a previous operator/session; do not preserve
    // successful results when the guarded capability is removed.
    setState("");
    setPhase("");
    setError("");
    busy.current = false;
  }, [enabled, token]);

  // Never render interactive controls for the ordinary read-only browser.
  if (enabled !== true) return null;

  async function perform(action: (isCurrent: () => boolean) => Promise<unknown>, selection?: "job" | "config") {
    if (enabled !== true || busy.current) return;
    const submittedSession = session.current;
    const selectedJob = jobSelection.current;
    const selectedConfig = configSelection.current;
    const isCurrent = () => (selection !== "job" ||
      (jobSelection.current.id === selectedJob.id && jobSelection.current.version === selectedJob.version)) &&
      (selection !== "config" || (configSelection.current.id === selectedConfig.id &&
       configSelection.current.version === selectedConfig.version)) &&
      session.current.enabled === true &&
      session.current.enabled === submittedSession.enabled &&
      session.current.token === submittedSession.token &&
      session.current.version === submittedSession.version;
    busy.current = true;
    setError("");
    try { await action(isCurrent); }
    catch { if (isCurrent()) setError("Guarded operation unavailable or rejected"); }
    finally {
      // A selection change invalidates the response, not ownership of the
      // in-flight request. Always release its busy claim in the same session.
      if (session.current.version === submittedSession.version) busy.current = false;
    }
  }
  function nativeConfig(): Record<string, unknown> {
    const value: unknown = JSON.parse(configJson);
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid native config");
    return value as Record<string, unknown>;
  }
  function request(): NativeRequest {
    if (!/^[A-Za-z0-9]{1,32}$/.test(symbol)) throw new Error("Invalid symbol");
    const start = Date.parse(from), end = Date.parse(to);
    if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end ||
        !/[zZ]|[+-]\d\d:\d\d$/.test(from) || !/[zZ]|[+-]\d\d:\d\d$/.test(to)) {
      throw new Error("Invalid UTC window");
    }
    return {exchange: "binance", market, symbol: symbol.toUpperCase(),
      period_start: from, period_end: to, strategy_timeframe: timeframe, intrabar_timeframe: intrabar};
  }
  return <section aria-label="Experimental guarded runs and configurations">
    <h3>Experimental guarded native operations</h3>
    <p>Server-side opt-in and separate certification are required. Cancellation is unavailable after native execution starts; claims are never automatically replayed after restart.</p>
    <label htmlFor="guard-config-id">Configuration ID</label>
    <input id="guard-config-id" value={configId} onChange={e => {
      configSelection.current = {id: e.target.value, version: configSelection.current.version + 1};
      setConfigId(e.target.value);
      setConfigJson("{}");
      setState("");
      setError("");
    }} />
    <label htmlFor="guard-config-json">Native configuration JSON</label>
    <textarea id="guard-config-json" value={configJson} onChange={e => setConfigJson(e.target.value)} rows={8} />
    <button type="button" onClick={() => void perform(async isCurrent => {
      const selection = configSelection.current;
      const result = await loadGuardedConfig(enabled, token, configId);
      if (isCurrent() && configSelection.current.version === selection.version &&
          configSelection.current.id === selection.id) {
        setConfigJson(JSON.stringify(result, null, 2));
        setState("Validated saved configuration loaded for editing");
      }
    }, "config")}>Load saved native configuration</button>
    <button type="button" onClick={() => void perform(async isCurrent => {
      const result = await saveGuardedConfig(enabled, token, configId, nativeConfig());
      if (isCurrent()) setState(`Configuration ${result.config_id}: ${result.status}`);
    }, "config")}>Save native configuration</button>
    <label htmlFor="guard-job-id">Request ID</label>
    <input id="guard-job-id" value={jobId} onChange={e => {
      jobSelection.current = {id: e.target.value, version: jobSelection.current.version + 1};
      setJobId(e.target.value);
      setState("");
      setPhase("");
      setError("");
    }} />
    <label htmlFor="guard-symbol">Symbol</label>
    <input id="guard-symbol" value={symbol} onChange={e => setSymbol(e.target.value)} />
    <label htmlFor="guard-market">Market</label>
    <select id="guard-market" value={market} onChange={e => setMarket(e.target.value as typeof market)}>
      <option value="futures_um">USDT futures</option><option value="spot">Spot</option>
    </select>
    <label htmlFor="guard-from">Start ISO 8601 UTC</label>
    <input id="guard-from" value={from} onChange={e => setFrom(e.target.value)} />
    <label htmlFor="guard-to">End ISO 8601 UTC (exclusive)</label>
    <input id="guard-to" value={to} onChange={e => setTo(e.target.value)} />
    <label htmlFor="guard-timeframe">Strategy timeframe</label>
    <select id="guard-timeframe" value={timeframe} onChange={e => setTimeframe(e.target.value as typeof timeframe)}>
      <option value="15m">15m</option><option value="1h">1h</option><option value="4h">4h</option><option value="1d">1d</option>
    </select>
    <label htmlFor="guard-intrabar">Intrabar timeframe</label>
    <select id="guard-intrabar" value={intrabar} onChange={e => setIntrabar(e.target.value as typeof intrabar)}>
      <option value="1m">1m</option><option value="5m">5m</option><option value="15m">15m</option>
    </select>
    <button type="button" onClick={() => void perform(async isCurrent => {
      const selectedJob = jobSelection.current;
      const result = await submitGuardedRun(enabled, token, jobId, request(), nativeConfig());
      if (isCurrent() && jobSelection.current.version === selectedJob.version &&
          jobSelection.current.id === selectedJob.id) setState(result.status);
    }, "job")}>Submit native research run</button>
    <button type="button" onClick={() => void perform(async isCurrent => {
      const selectedJob = jobSelection.current;
      const result = await guardedStatus(enabled, token, jobId);
      if (isCurrent() && jobSelection.current.version === selectedJob.version &&
          jobSelection.current.id === selectedJob.id) setState(result.status);
    }, "job")}>Refresh status</button>
    <button type="button" onClick={() => void perform(async isCurrent => {
      const selectedJob = jobSelection.current;
      const result = await guardedProgress(enabled, token, jobId);
      if (isCurrent() && jobSelection.current.version === selectedJob.version &&
          jobSelection.current.id === selectedJob.id) setPhase(result.phase ?? "No stage available");
    }, "job")}>Refresh progress</button>
    <button type="button" onClick={() => void perform(async isCurrent => {
      const selectedJob = jobSelection.current;
      const result = await guardedCancel(enabled, token, jobId);
      if (isCurrent() && jobSelection.current.version === selectedJob.version &&
          jobSelection.current.id === selectedJob.id) setState(result.status);
    }, "job")}>Request cancellation</button>
    {state && <p role="status">Native operation state: {state}</p>}
    {phase && <p role="status">Latest native stage: {phase}</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
