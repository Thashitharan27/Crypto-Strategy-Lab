import React from "react";
import { createRoot } from "react-dom/client";
import { getReadOnly, type Health, type Symbols } from "./api";
import "./style.css";

const sections = ["Data Library", "Runs & Results", "Configurations", "Strategy Designer", "Trade Visualizer"] as const;
type Section = (typeof sections)[number];

function App() {
  const [section, setSection] = React.useState<Section>("Runs & Results");
  const [token, setToken] = React.useState("");
  const [connected, setConnected] = React.useState(false);
  const [symbols, setSymbols] = React.useState<string[]>([]);
  const [coverage, setCoverage] = React.useState<unknown[] | null>(null);
  const [coverageSymbol, setCoverageSymbol] = React.useState("BTCUSDT");
  const [coverageError, setCoverageError] = React.useState("");
  const [message, setMessage] = React.useState("Not connected");
  const [configId, setConfigId] = React.useState("");
  const [configSummary, setConfigSummary] = React.useState<{ sections: string[]; configVersion: string } | null>(null);
  const [configError, setConfigError] = React.useState("");
  const [runId, setRunId] = React.useState("");
  const [runInfo, setRunInfo] = React.useState<{ run_id?: string; status?: string } | null>(null);
  const [runError, setRunError] = React.useState("");

  async function loadConfig() {
    setConfigSummary(null);
    setConfigError("");
    if (!/^[A-Za-z0-9_-]{1,100}$/.test(configId)) {
      setConfigError("Enter a valid saved configuration ID");
      return;
    }
    try {
      const result = await getReadOnly<{config: Record<string, unknown>}>(`/api/v1/configs/${configId}`, token);
      const value = result.config;
      if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid config");
      const version = value.config_version ?? value.version ?? "Not specified";
      setConfigSummary({sections: Object.keys(value), configVersion: String(version)});
    } catch {
      setConfigError("Saved configuration unavailable or not accessible");
    }
  }

  async function loadRun() {
    setRunInfo(null);
    setRunError("");
    if (!/^[A-Za-z0-9_-]{1,100}$/.test(runId)) { setRunError("Enter a valid saved run folder ID"); return; }
    try {
      const value = await getReadOnly<{manifest: {run_id?: string; run_status?: string}; summary: unknown}>(`/api/v1/runs/${runId}`, token);
      setRunInfo({run_id: value.manifest.run_id, status: value.manifest.run_status});
    } catch { setRunError("Saved run unavailable or not accessible"); }
  }

  async function loadCoverage() {
    setCoverage(null);
    setCoverageError("");
    if (!connected) { setCoverageError("Connect to the local read-only API first"); return; }
    if (!/^[A-Za-z0-9]{1,32}$/.test(coverageSymbol)) {
      setCoverageError("Select a valid symbol");
      return;
    }
    const end = new Date();
    const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
    const query = new URLSearchParams({symbol: coverageSymbol, market: "futures_um",
      start: start.toISOString(), end: end.toISOString(), strategy_timeframe: "4h", intrabar_timeframe: "1m"});
    try {
      const result = await getReadOnly<{coverage: unknown[]}>(`/api/v1/catalog/coverage?${query.toString()}`, token);
      if (!Array.isArray(result.coverage)) throw new Error("Invalid coverage response");
      setCoverage(result.coverage);
    } catch {
      setCoverageError("Coverage unavailable for this symbol or time window");
    }
  }

  async function connect() {
    setConnected(false);
    setSymbols([]);
    try {
      const health = await getReadOnly<Health>("/api/v1/health", token);
      if (health.mode !== "read-only" || health.status !== "ok") throw new Error("Unexpected API mode");
      const catalog = await getReadOnly<Symbols>("/api/v1/catalog/symbols", token);
      setSymbols(catalog.symbols);
      setConnected(true);
      setMessage("Connected to local read-only API");
    } catch {
      setMessage("Local API unavailable or authorization rejected");
    }
  }

  return <main className="layout">
    <aside><h1>Crypto Strategy Lab</h1><p>Browser migration · read-only</p>
      <nav aria-label="Research sections">{sections.map(item =>
        <button key={item} type="button" aria-current={section === item ? "page" : undefined} onClick={() => setSection(item)}>{item}</button>
      )}</nav>
    </aside>
    <section aria-live="polite"><header><small>RESEARCH WORKSPACE</small><h2>{section}</h2></header>
      <div className="connection">
        <label htmlFor="local-token">Local session token</label>
        <input id="local-token" type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} placeholder="Provided by your local API session" />
        <button type="button" onClick={() => void connect()} disabled={!token}>Connect read-only</button>
        <p role="status">{message}</p>
      </div>
      {section === "Configurations" && connected && <div className="connection">
        <label htmlFor="config-id">Saved configuration ID</label>
        <input id="config-id" value={configId} onChange={e => setConfigId(e.target.value)} placeholder="Configuration filename without .json" />
        <button type="button" onClick={() => void loadConfig()}>Inspect configuration</button>
        {configError && <p role="alert">{configError}</p>}
        {configSummary && <div><h3>Validated configuration</h3><p>Version: {configSummary.configVersion}</p><p>Sections: {configSummary.sections.join(", ")}</p></div>}
      </div>}
      {section === "Runs & Results" && connected && <div className="connection">
        <label htmlFor="run-id">Completed run folder ID</label>
        <input id="run-id" value={runId} onChange={e => setRunId(e.target.value)} placeholder="BTCUSDT_4h_…" />
        <button type="button" onClick={() => void loadRun()}>Read completed run</button>
        {runError && <p role="alert">{runError}</p>}
        {runInfo && <div><h3>Verified saved run</h3><p>Run ID: {runInfo.run_id ?? "Unavailable"}</p><p>Status: {runInfo.status ?? "Not specified"}</p></div>}
      </div>}
      {section === "Data Library" && connected ? <div><h3>Available symbols</h3><ul>{symbols.map(symbol => <li key={symbol}>{symbol}</li>)}</ul>
        <div className="connection"><label htmlFor="coverage-symbol">Data coverage symbol</label>
          <input id="coverage-symbol" value={coverageSymbol} onChange={e => setCoverageSymbol(e.target.value)} />
          <button type="button" onClick={() => void loadCoverage()}>Check last 30 days coverage (4h / 1m)</button>
          {coverageError && <p role="alert">{coverageError}</p>}
          {coverage && <p role="status">Coverage records returned: {coverage.length}. Data Library stays read-only.</p>}
        </div>
      </div> :
        <p>This section is being migrated. The existing Python engine and desktop application remain authoritative.</p>}
      <p>No strategy execution or configuration editing is enabled.</p>
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
