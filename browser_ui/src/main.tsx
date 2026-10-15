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
  const [coverageStart, setCoverageStart] = React.useState("2020-06-01");
  const [coverageEnd, setCoverageEnd] = React.useState("2026-09-01");
  const [coverageError, setCoverageError] = React.useState("");
  const [message, setMessage] = React.useState("Not connected");
  const [configId, setConfigId] = React.useState("");
  const [configSummary, setConfigSummary] = React.useState<{ sections: string[]; configVersion: string } | null>(null);
  const [configError, setConfigError] = React.useState("");
  const [runId, setRunId] = React.useState("");
  const [runInfo, setRunInfo] = React.useState<{ run_id?: string; status?: string } | null>(null);
  const [runError, setRunError] = React.useState("");
  const [runMetrics, setRunMetrics] = React.useState<{ trades: number; winRate: number; netPnl: number } | null>(null);
  const [runRisk, setRunRisk] = React.useState<{profitFactor?: number; drawdown?: number; fees?: number} | null>(null);

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
    setRunMetrics(null);
    setRunRisk(null);
    setRunError("");
    if (!/^[A-Za-z0-9_-]{1,100}$/.test(runId)) { setRunError("Enter a valid saved run folder ID"); return; }
    try {
      const value = await getReadOnly<{manifest: {run_id?: string; run_status?: string}; summary: Record<string, unknown>}>(`/api/v1/runs/${runId}`, token);
      setRunInfo({run_id: value.manifest.run_id, status: value.manifest.run_status});
      const {total_trades, win_rate, net_pnl, profit_factor, maximum_drawdown_percentage, total_fees} = value.summary;
      const safeMetric = (n: unknown) => typeof n === "number" && Number.isFinite(n) ? n : undefined;
      const profitFactor = safeMetric(profit_factor);
      const drawdown = safeMetric(maximum_drawdown_percentage);
      const fees = safeMetric(total_fees);
      setRunRisk({
        profitFactor: profitFactor !== undefined && profitFactor >= 0 ? profitFactor : undefined,
        drawdown: drawdown !== undefined && drawdown <= 0 ? drawdown : undefined,
        fees: fees !== undefined && fees >= 0 ? fees : undefined,
      });
      if ([total_trades, win_rate, net_pnl].every(v => typeof v === "number" && Number.isFinite(v)) &&
          (total_trades as number) >= 0 && Number.isInteger(total_trades as number) &&
          (win_rate as number) >= 0 && (win_rate as number) <= 1) {
        setRunMetrics({trades: total_trades as number, winRate: win_rate as number, netPnl: net_pnl as number});
      }
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
    const validDate = (value: string) => /^\\d{4}-\\d{2}-\\d{2}$/.test(value) && !Number.isNaN(Date.parse(value + "T00:00:00Z")) && new Date(value + "T00:00:00Z").toISOString().slice(0, 10) === value;
    if (!validDate(coverageStart) || !validDate(coverageEnd) || coverageStart >= coverageEnd) {
      setCoverageError("Select valid dates with the start before the end");
      return;
    }
    const start = new Date(coverageStart + "T00:00:00Z");
    const end = new Date(coverageEnd + "T00:00:00Z");
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
        {runInfo && <div><h3>Verified saved run</h3><p>Run ID: {runInfo.run_id ?? "Unavailable"}</p><p>Status: {runInfo.status ?? "Not specified"}</p>
          {runMetrics && <div aria-label="Saved run summary"><p>Trades: {runMetrics.trades}</p><p>Win rate: {(runMetrics.winRate * 100).toFixed(2)}%</p><p>Net P&L: {runMetrics.netPnl.toFixed(2)} (report currency)</p></div>}
          {runRisk && <div aria-label="Saved run risk metrics">
            {runRisk.profitFactor !== undefined && <p>Profit factor: {runRisk.profitFactor.toFixed(2)}</p>}
            {runRisk.drawdown !== undefined && <p>Maximum drawdown: {runRisk.drawdown.toFixed(2)}%</p>}
            {runRisk.fees !== undefined && <p>Total fees: {runRisk.fees.toFixed(2)} (report currency)</p>}
          </div>}
        </div>}
      </div>}
      {section === "Data Library" && connected ? <div><h3>Available symbols</h3><ul>{symbols.map(symbol => <li key={symbol}>{symbol}</li>)}</ul>
        <div className="connection"><label htmlFor="coverage-symbol">Data coverage symbol</label>
          <input id="coverage-symbol" value={coverageSymbol} onChange={e => setCoverageSymbol(e.target.value)} />
          <label htmlFor="coverage-start">Start date (UTC)</label>
          <input id="coverage-start" type="date" value={coverageStart} onChange={e => setCoverageStart(e.target.value)} />
          <label htmlFor="coverage-end">End date (UTC, exclusive)</label>
          <input id="coverage-end" type="date" value={coverageEnd} onChange={e => setCoverageEnd(e.target.value)} />
          <button type="button" onClick={() => void loadCoverage()}>Check coverage (4h / 1m)</button>
          {coverageError && <p role="alert">{coverageError}</p>}
          {coverage && <p role="status">Coverage records returned: {coverage.length}. Data Library stays read-only.</p>}
        </div>
      </div> : null}
      {(section === "Strategy Designer" || section === "Trade Visualizer") &&
        <p>This section is being migrated. The existing Python engine and desktop application remain authoritative.</p>}
      <p>No strategy execution or configuration editing is enabled.</p>
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
