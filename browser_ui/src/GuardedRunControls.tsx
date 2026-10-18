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
  verified_run_folder_id?: string;
};
const ID = /^[A-Za-z0-9_-]{1,100}$/;

const JOB_STATES = new Set([
  "ACCEPTED", "QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED",
  "CANCELLATION_UNAVAILABLE", "RECOVERY_UNVERIFIED",
]);
function safeJobState(response: JobState, selectedId: string): string {
  if (!response || response.request_id !== selectedId ||
      !JOB_STATES.has(response.status)) {
    throw new Error("Invalid native job status response");
  }
  return response.status;
}

function describeJobState(status: string): string {
  if (status === "ACCEPTED") return "Submission accepted. Native completion is not yet confirmed.";
  if (status === "RECOVERY_UNVERIFIED") return "Recovery unverified: a request claim survived restart, but its native execution and saved outputs have not been independently verified. Do not resubmit or assume completion.";
  if (status === "CANCELLATION_UNAVAILABLE") return "Cancellation unavailable: native execution may be running. No cancellation is confirmed.";
  if (status === "COMPLETED") return "Native worker completed in this session. Inspect verified saved results separately.";
  if (status === "FAILED") return "Native worker failed. Check sanitized service status; no successful saved output is implied.";
  if (status === "CANCELLED") return "Queued native job cancelled before execution.";
  return "Native job state: " + status;
}

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

/** A separate, explicit read of the existing verified completed-run endpoint.
 * Request IDs are not necessarily output-folder IDs. No mapping is guessed.
 */
export async function inspectVerifiedSavedRun(enabled: boolean, token: string, folderId: string) {
  requireGuardedSession(enabled, token);
  const response = await getReadOnly<{
    manifest?: {run_id?: unknown; run_status?: unknown};
    summary?: unknown;
  }>(`/api/v1/runs/${safeId(folderId)}`, token);
  if (!response || !response.manifest ||
      typeof response.manifest !== "object" || Array.isArray(response.manifest) ||
      typeof response.manifest.run_id !== "string" ||
      !response.summary || typeof response.summary !== "object" ||
      Array.isArray(response.summary)) {
    throw new Error("Invalid verified saved-run response");
  }
  return {
    folderId,
    nativeRunId: response.manifest.run_id,
    runStatus: typeof response.manifest.run_status === "string"
      ? response.manifest.run_status : "not specified",
  };
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
  return guardedRequest<{phase?: unknown}>(enabled, token, "GET", `/api/v1/guarded/jobs/${safeId(id)}/progress`);
}

function safeNativeStage(result: {phase?: unknown}): string {
  // Match the server's bounded stage allowlist. Never show native free-form
  // diagnostics, filesystem paths or unexpected progress response bodies.
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    throw new Error("Invalid native progress response");
  }
  if (result.phase === undefined) return "No stage available";
  if (typeof result.phase !== "string" || !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(result.phase)) {
    throw new Error("Invalid native progress stage");
  }
  return result.phase;
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
  const [savedRunFolderId, setSavedRunFolderId] = React.useState("");
  const savedRunSelection = React.useRef({id: "", version: 0});
  const [verifiedSavedRun, setVerifiedSavedRun] = React.useState("");
  const [nativeVerifiedFolder, setNativeVerifiedFolder] = React.useState("");
  const [savedRunError, setSavedRunError] = React.useState("");
  const jobSelection = React.useRef({id: "", version: 0});
  const [symbol, setSymbol] = React.useState("BTCUSDT");
  const [market, setMarket] = React.useState<"spot" | "futures_um">("futures_um");
  const [from, setFrom] = React.useState("2025-01-01T00:00:00Z");
  const [to, setTo] = React.useState("2025-01-02T00:00:00Z");
  const [timeframe, setTimeframe] = React.useState<NativeRequest["strategy_timeframe"]>("4h");
  const [intrabar, setIntrabar] = React.useState<NativeRequest["intrabar_timeframe"]>("1m");
  const [state, setState] = React.useState("");
  const [phase, setPhase] = React.useState("");
  const [recoveryUnverified, setRecoveryUnverified] = React.useState(false);
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
    // Changing operators must discard editable native configuration and
    // invalidate pending loads, not just clear status messages.
    configSelection.current = {
      id: "", version: configSelection.current.version + 1,
    };
    setConfigId("");
    setConfigJson("{}");
    jobSelection.current = {id: "", version: jobSelection.current.version + 1};
    savedRunSelection.current = {id: "", version: savedRunSelection.current.version + 1};
    setJobId("");
    setSavedRunFolderId("");
    setState("");
    setPhase("");
    setRecoveryUnverified(false);
    setError("");
    setVerifiedSavedRun("");
    setNativeVerifiedFolder("");
    setSavedRunError("");
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
    <textarea id="guard-config-json" value={configJson} onChange={e => {
      // A pending server load must not overwrite a newer manual edit.
      configSelection.current = {
        id: configSelection.current.id, version: configSelection.current.version + 1,
      };
      setConfigJson(e.target.value);
    }} rows={8} />
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
      setNativeVerifiedFolder("");
      setState("");
      setRecoveryUnverified(false);
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
          jobSelection.current.id === selectedJob.id) {
        const status = safeJobState(result, jobId);
        setState(status);
        setNativeVerifiedFolder(status === "COMPLETED" &&
          typeof result.verified_run_folder_id === "string" &&
          ID.test(result.verified_run_folder_id) ? result.verified_run_folder_id : "");
        setRecoveryUnverified(status === "RECOVERY_UNVERIFIED");
        if (status === "RECOVERY_UNVERIFIED") setPhase("");
      }
    }, "job")} disabled={recoveryUnverified}>Submit native research run</button>
    <button type="button" onClick={() => void perform(async isCurrent => {
      const selectedJob = jobSelection.current;
      const result = await guardedStatus(enabled, token, jobId);
      if (isCurrent() && jobSelection.current.version === selectedJob.version &&
          jobSelection.current.id === selectedJob.id) {
        const status = safeJobState(result, jobId);
        setState(status);
        setNativeVerifiedFolder(status === "COMPLETED" &&
          typeof result.verified_run_folder_id === "string" &&
          ID.test(result.verified_run_folder_id) ? result.verified_run_folder_id : "");
        setRecoveryUnverified(status === "RECOVERY_UNVERIFIED");
        if (status === "RECOVERY_UNVERIFIED") setPhase("");
      }
    }, "job")}>Refresh status</button>
    <button type="button" onClick={() => void perform(async isCurrent => {
      const selectedJob = jobSelection.current;
      const result = await guardedProgress(enabled, token, jobId);
      if (isCurrent() && jobSelection.current.version === selectedJob.version &&
          jobSelection.current.id === selectedJob.id) setPhase(safeNativeStage(result));
    }, "job")} disabled={recoveryUnverified}>Refresh progress</button>
    <button type="button" onClick={() => void perform(async isCurrent => {
      const selectedJob = jobSelection.current;
      const result = await guardedCancel(enabled, token, jobId);
      if (isCurrent() && jobSelection.current.version === selectedJob.version &&
          jobSelection.current.id === selectedJob.id) {
        const status = safeJobState(result, jobId);
        setState(status);
        setNativeVerifiedFolder(status === "COMPLETED" &&
          typeof result.verified_run_folder_id === "string" &&
          ID.test(result.verified_run_folder_id) ? result.verified_run_folder_id : "");
        setRecoveryUnverified(status === "RECOVERY_UNVERIFIED");
        if (status === "RECOVERY_UNVERIFIED") setPhase("");
      }
    }, "job")} disabled={recoveryUnverified}>Request cancellation</button>
    {nativeVerifiedFolder && <p role="status">Native job output verified in this session: folder {nativeVerifiedFolder}. Select this folder for independent read-only inspection.</p>}
    {nativeVerifiedFolder && <button type="button" onClick={() => {
      savedRunSelection.current = {id: nativeVerifiedFolder, version: savedRunSelection.current.version + 1};
      setSavedRunFolderId(nativeVerifiedFolder);
      setVerifiedSavedRun("");
      setSavedRunError("");
    }}>Select verified native output folder</button>}
    <label htmlFor="guard-saved-run-folder">Saved run folder ID (not the request ID)</label>
    <input id="guard-saved-run-folder" value={savedRunFolderId} onChange={event => {
      savedRunSelection.current = {
        id: event.target.value, version: savedRunSelection.current.version + 1,
      };
      setSavedRunFolderId(event.target.value);
      setVerifiedSavedRun("");
      setSavedRunError("");
    }} />
    <button type="button" onClick={() => {
      const originatingSession = session.current;
      const selection = savedRunSelection.current;
      setSavedRunError("");
      setVerifiedSavedRun("");
      void inspectVerifiedSavedRun(enabled, token, savedRunFolderId).then(result => {
        if (session.current.version === originatingSession.version &&
            session.current.enabled && savedRunSelection.current.version === selection.version &&
            savedRunSelection.current.id === selection.id) {
          setVerifiedSavedRun(`Verified saved run folder ${result.folderId}; native run ID ${result.nativeRunId}; manifest status ${result.runStatus}`);
        }
      }).catch(() => {
        if (session.current.version === originatingSession.version &&
            session.current.enabled && savedRunSelection.current.version === selection.version &&
            savedRunSelection.current.id === selection.id) {
          setSavedRunError("Saved run not available or verification rejected");
        }
      });
    }}>Inspect verified saved run</button>
    {verifiedSavedRun && <p role="status">{verifiedSavedRun}</p>}
    {savedRunError && <p role="alert">{savedRunError}</p>}
    {state && <p role="status">{describeJobState(state)}</p>}
    {phase && !recoveryUnverified && <p role="status">Latest native stage: {phase}</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
