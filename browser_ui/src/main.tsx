import React from "react";
import { createRoot } from "react-dom/client";
import { getReadOnly, openVerifiedVisualizer, type Health, type Symbols } from "./api";
import { GuardedRunControls } from "./GuardedRunControls";
import "./style.css";

const sections = ["Setup", "Data Library", "Runs & Results", "Configurations", "Strategy Designer", "Research Features", "Risk & Execution", "Portfolio", "Integrations", "Trade Visualizer"] as const;
type Section = (typeof sections)[number];
type CoverageRecord = {symbol?: string; dataset?: string; interval?: string | null; state?: string; archive_count?: number; first_period?: string | null; last_period?: string | null};
type StrategyCapability = {
  rule_group_model: {families: string[]; conditions_inside_group: string; groups_inside_family: string};
  signal_strategies: {id: string; display_name: string}[];
  market_permissions: string[];
  indicators: Record<string, {display_name: string; type: string; conditions: string[]; values?: string[] | null; supports_sr_timeframe?: boolean}>;
};
type FeatureCapability = {
  name: string; version: string; required_datasets: string[]; optional_datasets: string[];
  required_features: string[]; warmup_bars: number; availability_rule: string;
};
type Capabilities = {mode: string; strategy: StrategyCapability; features: FeatureCapability[]};
type ReleaseCapabilities = {execution: boolean; configuration_editing: boolean};

function App() {
  const [section, setSection] = React.useState<Section>("Runs & Results");
  const [evidenceQuery, setEvidenceQuery] = React.useState("");
  const [featureQuery, setFeatureQuery] = React.useState("");
  const [token, setToken] = React.useState("");
  const [connected, setConnected] = React.useState(false);
  const [releaseCapabilities, setReleaseCapabilities] = React.useState<ReleaseCapabilities | null>(null);
  const connectRequest = React.useRef(0);
  const [symbols, setSymbols] = React.useState<string[]>([]);
  const [capabilities, setCapabilities] = React.useState<Capabilities | null>(null);
  const [coverage, setCoverage] = React.useState<CoverageRecord[] | null>(null);
  const [coverageSymbol, setCoverageSymbol] = React.useState("BTCUSDT");
  const [coverageStart, setCoverageStart] = React.useState("2020-06-01");
  const [coverageEnd, setCoverageEnd] = React.useState("2026-09-01");
  const [coverageError, setCoverageError] = React.useState("");
  const [coverageQueryLabel, setCoverageQueryLabel] = React.useState("");
  const coverageRequest = React.useRef(0);
  const [coverageStatusFilter, setCoverageStatusFilter] = React.useState("ALL");
  const [incompleteFirst, setIncompleteFirst] = React.useState(false);
  const [message, setMessage] = React.useState("Not connected");
  const [configId, setConfigId] = React.useState("");
  const [configSection, setConfigSection] = React.useState("");
  const [configSummary, setConfigSummary] = React.useState<{ sections: string[]; configVersion: string } | null>(null);
  const [configError, setConfigError] = React.useState("");
  const [configDetails, setConfigDetails] = React.useState<Record<string, unknown> | null>(null);
  const configRequest = React.useRef(0);
  type PortfolioCandidate = {run_id: string; run_folder_id: string; symbol: string; strategy_timeframe?: string | null; candidate_rows: number; completed_at?: string | null; sampling_mode: string};
  const [portfolioCandidates, setPortfolioCandidates] = React.useState<PortfolioCandidate[] | null>(null);
  const [portfolioError, setPortfolioError] = React.useState("");
  const portfolioRequest = React.useRef(0);
  const [runId, setRunId] = React.useState("");
  const [visualizerRunId, setVisualizerRunId] = React.useState("");
  const [visualizerUrl, setVisualizerUrl] = React.useState("");
  const [visualizerError, setVisualizerError] = React.useState("");
  const visualizerRequest = React.useRef(0);
  const [runInfo, setRunInfo] = React.useState<{ run_id?: string; status?: string } | null>(null);
  const [runError, setRunError] = React.useState("");
  const runRequest = React.useRef(0);
  const [runMetrics, setRunMetrics] = React.useState<{ trades: number; winRate?: number; netPnl?: number; totalNetR?: number; endingEquity?: number; totalReturnPercentage?: number } | null>(null);
  const [runRisk, setRunRisk] = React.useState<{profitFactor?: number; drawdown?: number; fees?: number} | null>(null);

  async function loadConfig() {
    const requestId = ++configRequest.current;
    setConfigSummary(null);
    setConfigDetails(null);
    setConfigSection("");
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
      if (requestId !== configRequest.current) return;
      setConfigSummary({sections: Object.keys(value), configVersion: String(version)});
      setConfigDetails(value);
    } catch {
      if (requestId !== configRequest.current) return;
      setConfigError("Saved configuration unavailable or not accessible");
    }
  }

  async function loadRun() {
    const requestId = ++runRequest.current;
    setRunInfo(null);
    setRunMetrics(null);
    setRunRisk(null);
    setRunError("");
    if (!/^[A-Za-z0-9_-]{1,100}$/.test(runId)) { setRunError("Enter a valid saved run folder ID"); return; }
    try {
      const value = await getReadOnly<{manifest: {run_id?: string; run_status?: string}; summary: Record<string, unknown>}>(`/api/v1/runs/${runId}`, token);
      if (requestId !== runRequest.current) return;
      setRunInfo({run_id: value.manifest.run_id, status: value.manifest.run_status});
      const {total_trades, win_rate, net_pnl, total_net_r, ending_equity, total_return_percentage, profit_factor, maximum_drawdown_percentage, total_fees} = value.summary;
      const safeMetric = (n: unknown) => typeof n === "number" && Number.isFinite(n) ? n : undefined;
      const profitFactor = safeMetric(profit_factor);
      const drawdown = safeMetric(maximum_drawdown_percentage);
      const fees = safeMetric(total_fees);
      setRunRisk({
        profitFactor: profitFactor !== undefined && profitFactor >= 0 ? profitFactor : profit_factor === "Infinity" ? Number.POSITIVE_INFINITY : undefined,
        drawdown: drawdown !== undefined && drawdown <= 0 ? drawdown : undefined,
        fees: fees !== undefined && fees >= 0 ? fees : undefined,
      });
      if (typeof total_trades === "number" && Number.isInteger(total_trades) && total_trades >= 0) {
        const rate = safeMetric(win_rate);
        setRunMetrics({
          trades: total_trades,
          winRate: rate !== undefined && rate >= 0 && rate <= 1 ? rate : undefined,
          netPnl: safeMetric(net_pnl),
          totalNetR: safeMetric(total_net_r),
          endingEquity: safeMetric(ending_equity),
          totalReturnPercentage: safeMetric(total_return_percentage),
        });
      }
    } catch { if (requestId === runRequest.current) setRunError("Saved run unavailable or not accessible"); }
  }

  async function loadCoverage() {
    const requestId = ++coverageRequest.current;
    setCoverage(null);
    setCoverageQueryLabel("");
    setCoverageError("");
    if (!connected) { setCoverageError("Connect to the local read-only API first"); return; }
    if (!/^[A-Za-z0-9]{1,32}$/.test(coverageSymbol)) {
      setCoverageError("Select a valid symbol");
      return;
    }
    const validDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value + "T00:00:00Z")) && new Date(value + "T00:00:00Z").toISOString().slice(0, 10) === value;
    if (!validDate(coverageStart) || !validDate(coverageEnd) || coverageStart >= coverageEnd) {
      setCoverageError("Select valid dates with the start before the end");
      return;
    }
    const start = new Date(coverageStart + "T00:00:00Z");
    const end = new Date(coverageEnd + "T00:00:00Z");
    const query = new URLSearchParams({symbol: coverageSymbol, market: "futures_um",
      start: start.toISOString(), end: end.toISOString(), strategy_timeframe: "4h", intrabar_timeframe: "1m"});
    try {
      const result = await getReadOnly<{coverage: CoverageRecord[]}>(`/api/v1/catalog/coverage?${query.toString()}`, token);
      if (!Array.isArray(result.coverage) || result.coverage.some(item => !item || typeof item !== "object" || Array.isArray(item))) throw new Error("Invalid coverage response");
      if (requestId !== coverageRequest.current) return;
      setCoverage(result.coverage);
      setCoverageQueryLabel(`${coverageSymbol.toUpperCase()} · ${coverageStart} to ${coverageEnd} UTC (end exclusive) · 4h / 1m`);
    } catch {
      if (requestId !== coverageRequest.current) return;
      setCoverageError("Coverage unavailable for this symbol or time window");
    }
  }

  async function openVisualizer() {
    const requestId = ++visualizerRequest.current;
    setVisualizerUrl("");
    setVisualizerError("");
    if (!connected) { setVisualizerError("Connect read-only first"); return; }
    try {
      const url = await openVerifiedVisualizer(visualizerRunId, token);
      if (requestId === visualizerRequest.current) setVisualizerUrl(url);
    } catch {
      if (requestId === visualizerRequest.current) setVisualizerError("Verified visualizer session unavailable");
    }
  }

  async function loadPortfolioCandidates() {
    const requestId = ++portfolioRequest.current;
    setPortfolioError("");
    setPortfolioCandidates(null);
    try {
      const response = await getReadOnly<{candidates: PortfolioCandidate[]}>("/api/v1/portfolio/candidates", token);
      if (requestId !== portfolioRequest.current) return;
      if (!Array.isArray(response.candidates)) throw new Error("Invalid portfolio response");
      setPortfolioCandidates(response.candidates);
    } catch {
      if (requestId === portfolioRequest.current) setPortfolioError("Could not load verified completed portfolio candidates");
    }
  }

  async function connect() {
    const requestId = ++connectRequest.current;
    // Invalidate in-flight catalog reads before switching local API sessions.
    ++coverageRequest.current;
    ++configRequest.current;
    ++runRequest.current;
    ++visualizerRequest.current;
    ++portfolioRequest.current;
    setPortfolioCandidates(null);
    setPortfolioError("");
    setVisualizerUrl("");
    setVisualizerError("");
    setConfigSummary(null);
    setConfigDetails(null);
    setConfigError("");
    setRunInfo(null);
    setRunMetrics(null);
    setRunRisk(null);
    setRunError("");
    setCoverage(null);
    setCoverageQueryLabel("");
    setCoverageError("");
    setConnected(false);
    setReleaseCapabilities(null);
    setSymbols([]);
    setCapabilities(null);
    try {
      const health = await getReadOnly<Health>("/api/v1/health", token);
      if (health.mode !== "read-only" || health.status !== "ok") throw new Error("Unexpected API mode");
      const [catalog, capabilityData, releaseData] = await Promise.all([
        getReadOnly<Symbols>("/api/v1/catalog/symbols", token),
        getReadOnly<Capabilities>("/api/v1/capabilities", token),
        getReadOnly<ReleaseCapabilities>("/api/v1/release/capabilities", token),
      ]);
      if (capabilityData.mode !== "read-only" || !Array.isArray(capabilityData.features) || !capabilityData.strategy?.indicators) throw new Error("Invalid capability metadata");
      if (!releaseData || typeof releaseData.execution !== "boolean" || typeof releaseData.configuration_editing !== "boolean") throw new Error("Invalid release capability metadata");
      if (requestId !== connectRequest.current) return;
      setSymbols(catalog.symbols);
      setCapabilities(capabilityData);
      setReleaseCapabilities(releaseData);
      setConnected(true);
      setMessage("Connected to local read-only API");
    } catch {
      if (requestId !== connectRequest.current) return;
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
        <input id="local-token" type="password" autoComplete="off" value={token} onChange={event => { ++connectRequest.current; ++configRequest.current; ++coverageRequest.current; ++runRequest.current; ++portfolioRequest.current; ++visualizerRequest.current; setVisualizerUrl(""); setVisualizerError(""); setToken(event.target.value); setConnected(false); setReleaseCapabilities(null); setSymbols([]); setCapabilities(null); setConfigSummary(null); setConfigDetails(null); setConfigSection(""); setConfigError(""); setRunInfo(null); setRunMetrics(null); setRunRisk(null); setRunError(""); setPortfolioCandidates(null); setPortfolioError(""); setCoverage(null); setCoverageError(""); setCoverageQueryLabel(""); setMessage("Not connected"); }} placeholder="Provided by your local API session" />
        <button type="button" onClick={() => void connect()} disabled={!token}>Connect read-only</button>
        <p role="status">{message}</p>
      </div>
      {section === "Setup" && connected && <div className="connection">
        <h3>Saved run setup (read-only)</h3>
        <p>Setup is owned by the validated Python configuration. Inspect a saved configuration in Configurations to review its existing data settings here; no independent browser defaults are applied.</p>
        {!configDetails && <p>No configuration selected. Open Configurations and inspect a saved configuration first.</p>}
        {configDetails && Object.prototype.hasOwnProperty.call(configDetails, "data") &&
          <pre aria-label="Saved run data configuration" style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: "24rem", overflowY: "auto"}}>{JSON.stringify(configDetails.data, null, 2)}</pre>}
        {configDetails && !Object.prototype.hasOwnProperty.call(configDetails, "data") &&
          <p>No data section is present in this validated configuration snapshot.</p>}
        <p>Setup cannot be edited or applied from the browser.</p>
      </div>}
      {section === "Configurations" && connected && <div className="connection">
        <label htmlFor="config-id">Saved configuration ID</label>
        <input id="config-id" value={configId} onChange={e => { ++configRequest.current; setConfigId(e.target.value); setConfigSummary(null); setConfigDetails(null); setConfigSection(""); setConfigError(""); }} placeholder="Configuration filename without .json" />
        <button type="button" disabled={!connected} onClick={() => void loadConfig()}>Inspect configuration</button>
        {configError && <p role="alert">{configError}</p>}
        {configSummary && <div><h3>Validated configuration</h3><p>Version: {configSummary.configVersion}</p><p>Sections: {configSummary.sections.join(", ")}</p><p>Read-only snapshot from the existing CSL configuration reader. No save, normalization, or execution is performed by the browser.</p>{configDetails && <><label htmlFor="config-section">Inspect one saved configuration section</label><select id="config-section" value={configSection} onChange={event => setConfigSection(event.target.value)}><option value="">Choose a section</option>{configSummary.sections.map(name => <option key={name} value={name}>{name}</option>)}</select>{configSection && Object.prototype.hasOwnProperty.call(configDetails, configSection) && configDetails[configSection] !== null && typeof configDetails[configSection] === "object" && !Array.isArray(configDetails[configSection]) && <table aria-label="Selected configuration fields"><caption>Saved fields from {configSection} (read-only)</caption><thead><tr><th>Original field</th><th>Saved value</th></tr></thead><tbody>{Object.entries(configDetails[configSection] as Record<string, unknown>).map(([key, value]) => <tr key={key}><td><code>{key}</code></td><td><code>{JSON.stringify(value) ?? "undefined"}</code></td></tr>)}</tbody></table>}{configSection && Object.prototype.hasOwnProperty.call(configDetails, configSection) && <pre aria-label="Selected configuration section" style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: "24rem", overflowY: "auto"}}>{JSON.stringify(configDetails[configSection], null, 2)}</pre>}</>}{configDetails && <details><summary>Inspect saved configuration values</summary><pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: "24rem", overflowY: "auto"}}>{JSON.stringify(configDetails, null, 2)}</pre></details>}</div>}
      </div>}
      {section === "Strategy Designer" && connected && configDetails && <div className="connection">
        <h3>Saved strategy settings (read-only)</h3>
        <p>Projection of the currently inspected configuration. Original field names and nested values remain unchanged.</p>
        {["strategy", "features"].filter(name => Object.prototype.hasOwnProperty.call(configDetails, name)).map(name =>
          <details key={name}><summary>{name === "strategy" ? "Strategy and policy configuration" : "Feature-owned selection and confirmation settings"}</summary>
            <pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: "24rem", overflowY: "auto"}}>{JSON.stringify(configDetails[name], null, 2)}</pre>
          </details>
        )}
        <p>Feature-owned switches are displayed for context only; they are not a second copy of editable settings.</p>
      </div>}
      {section === "Research Features" && connected && configDetails && Object.prototype.hasOwnProperty.call(configDetails, "features") && <div className="connection">
        <h3>Saved research feature settings (read-only)</h3>
        <pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: "24rem", overflowY: "auto"}}>{JSON.stringify(configDetails.features, null, 2)}</pre>
      </div>}
      {section === "Risk & Execution" && connected && <div className="connection">
        <h3>Saved risk and execution settings (read-only)</h3>
        <p>This view reads the original validated configuration snapshot. Risk sizing, stops, targets, costs, fills and exits remain owned by the existing Python engine and desktop controls.</p>
        {!configDetails && <p>Inspect a saved configuration in Configurations to view its original execution settings here.</p>}
        {configDetails && Object.prototype.hasOwnProperty.call(configDetails, "execution") &&
          <pre aria-label="Saved execution configuration" style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: "24rem", overflowY: "auto"}}>{JSON.stringify(configDetails.execution, null, 2)}</pre>}
        {configDetails && !Object.prototype.hasOwnProperty.call(configDetails, "execution") &&
          <p>No execution section is present in this validated configuration snapshot.</p>}
        <p>No execution settings can be edited or applied from the browser.</p>
      </div>}
      {section === "Integrations" && connected && <div className="connection">
        <h3>Integration boundaries (read-only)</h3>
        <p>This section describes which existing Python services own integration functionality. It does not check whether external accounts are connected or expose credentials.</p>
        <table><thead><tr><th>Integration</th><th>Existing owner</th><th>Browser boundary</th></tr></thead>
          <tbody>
            <tr><td>Market data and Data Lake</td><td>Existing application catalog and cache</td><td>Read-only symbols and coverage</td></tr>
            <tr><td>Completed runs and Portfolio</td><td>Existing completed-run readers and portfolio discovery</td><td>Verified metadata only; no replay</td></tr>
            <tr><td>ChatGPT connection</td><td>Desktop credential and connection services</td><td>Managed outside browser; no secret access</td></tr>
            <tr><td>MCP and automation</td><td>Existing control plane</td><td>No execution or write actions in browser</td></tr>
          </tbody>
        </table>
        <p>Connection health, account authorization and installation status are not inferred here. Setup and credentials remain in their existing services.</p>
      </div>}
      {section === "Portfolio" && connected && <div className="connection">
        <h3>Eligible finalized portfolio runs (read-only)</h3>
        <p>Uses verified Every Viable Entry resilience outputs from the configured completed-run folder. Discovery does not replay portfolios, rerun strategies, or modify results.</p>
        <button type="button" onClick={() => void loadPortfolioCandidates()}>Refresh eligible runs</button>
        {portfolioError && <p role="alert">{portfolioError}</p>}
        {portfolioCandidates && portfolioCandidates.length === 0 && <p>No eligible verified completed runs found.</p>}
        {portfolioCandidates && portfolioCandidates.length > 0 && <table>
          <thead><tr><th>Run ID</th><th>Symbol</th><th>Timeframe</th><th>Sampling mode</th><th>Candidates</th><th>Completed</th></tr></thead>
          <tbody>{portfolioCandidates.map((item, i) => <tr key={item.run_id + "-" + i}>
            <td><button type="button" onClick={() => {++runRequest.current; setRunId(item.run_folder_id); setRunInfo(null); setRunMetrics(null); setRunRisk(null); setRunError(""); setSection("Runs & Results");}} aria-label={`Inspect completed run ${item.run_id}`}>{item.run_id}</button></td><td>{item.symbol}</td><td>{item.strategy_timeframe || "—"}</td><td>{item.sampling_mode}</td>
            <td>{item.candidate_rows}</td><td>{item.completed_at || "—"}</td>
          </tr>)}</tbody>
        </table>}
        <p>Portfolio replay and risk settings remain in the existing desktop workspace.</p>
      </div>}
      {section === "Runs & Results" && connected && <div className="connection">
        <label htmlFor="run-id">Completed run folder ID</label>
        <input id="run-id" value={runId} onChange={e => {++runRequest.current; setRunId(e.target.value); setRunInfo(null); setRunMetrics(null); setRunRisk(null); setRunError("");}} placeholder="BTCUSDT_4h_…" />
        <button type="button" disabled={!connected} onClick={() => void loadRun()}>Read completed run</button>
        {runError && <p role="alert">{runError}</p>}
        {runInfo && <div><h3>Verified saved run</h3><p>Run ID: {runInfo.run_id ?? "Unavailable"}</p><p>Status: {runInfo.status ?? "Not specified"}</p><button type="button" onClick={() => {++visualizerRequest.current; setVisualizerRunId(runId); setVisualizerUrl(""); setVisualizerError(""); setSection("Trade Visualizer");}}>View in Trade Visualizer</button>
          {runMetrics && <div aria-label="Saved run summary"><p>Trades: {runMetrics.trades}</p>{runMetrics.winRate !== undefined && <p>Win rate: {(runMetrics.winRate * 100).toFixed(2)}%</p>}{runMetrics.netPnl !== undefined && <p>Net P&L: {runMetrics.netPnl.toFixed(2)} (report currency)</p>}{runMetrics.totalNetR !== undefined && <p>Total net R: {runMetrics.totalNetR.toFixed(2)}R</p>}{runMetrics.endingEquity !== undefined && <p>Ending equity: {runMetrics.endingEquity.toFixed(2)} (report currency)</p>}{runMetrics.totalReturnPercentage !== undefined && <p>Total return: {runMetrics.totalReturnPercentage.toFixed(2)}%</p>}</div>}
          {runRisk && <div aria-label="Saved run risk metrics">
            {runRisk.profitFactor !== undefined && <p>Profit factor: {Number.isFinite(runRisk.profitFactor) ? runRisk.profitFactor.toFixed(2) : "∞"}</p>}
            {runRisk.drawdown !== undefined && <p>Maximum drawdown: {runRisk.drawdown.toFixed(2)}%</p>}
            {runRisk.fees !== undefined && <p>Total fees: {runRisk.fees.toFixed(2)} (report currency)</p>}
          </div>}
        </div>}
      </div>}
      {section === "Data Library" && connected ? <div><h3>Available symbols</h3><ul>{symbols.map(symbol => <li key={symbol}>{symbol}</li>)}</ul>
        <div className="connection"><label htmlFor="coverage-symbol">Data coverage symbol</label>
          <input id="coverage-symbol" value={coverageSymbol} onChange={e => {++coverageRequest.current; setCoverageSymbol(e.target.value); setCoverage(null); setCoverageQueryLabel(""); setCoverageError("");}} />
          <label htmlFor="coverage-start">Start date (UTC)</label>
          <input id="coverage-start" type="date" value={coverageStart} onChange={e => {++coverageRequest.current; setCoverageStart(e.target.value); setCoverage(null); setCoverageQueryLabel(""); setCoverageError("");}} />
          <label htmlFor="coverage-end">End date (UTC, exclusive)</label>
          <input id="coverage-end" type="date" value={coverageEnd} onChange={e => {++coverageRequest.current; setCoverageEnd(e.target.value); setCoverage(null); setCoverageQueryLabel(""); setCoverageError("");}} />
          <button type="button" disabled={!connected} onClick={() => void loadCoverage()}>Check coverage (4h / 1m)</button>
          {coverageError && <p role="alert">{coverageError}</p>}
          {coverage && <div><p role="status">Coverage records returned: {coverage.length}. Data Library stays read-only.</p>
            <p aria-label="Coverage request scope">Requested: {coverageQueryLabel}</p>
            <p aria-label="Coverage availability summary">Available: {coverage.filter(row => row.state === "AVAILABLE").length} · Partial: {coverage.filter(row => row.state === "PARTIAL").length} · Unavailable: {coverage.filter(row => row.state === "UNAVAILABLE").length} · Unknown: {coverage.filter(row => !["AVAILABLE", "PARTIAL", "UNAVAILABLE"].includes(row.state ?? "")).length}</p>
            <label htmlFor="coverage-status-filter">Coverage status filter</label>
            <select id="coverage-status-filter" value={coverageStatusFilter} onChange={e => setCoverageStatusFilter(e.target.value)}>
              <option value="ALL">All records</option><option value="AVAILABLE">Available</option><option value="PARTIAL">Partial</option><option value="UNAVAILABLE">Unavailable</option><option value="UNKNOWN">Unknown</option>
            </select>
            <label htmlFor="coverage-incomplete-first"><input id="coverage-incomplete-first" type="checkbox" checked={incompleteFirst} onChange={e => setIncompleteFirst(e.target.checked)} /> Show incomplete coverage first</label>
            {coverage.length === 0 && <p role="status">No catalog coverage records were returned for this symbol and period. This does not establish missing candles.</p>}
            {coverage.length > 0 && coverageStatusFilter !== "ALL" && !coverage.some(record => coverageStatusFilter === "UNKNOWN" ? !["AVAILABLE", "PARTIAL", "UNAVAILABLE"].includes(record.state ?? "") : record.state === coverageStatusFilter) && <p role="status">No coverage records match this status filter.</p>}
            <table><caption>Saved catalog coverage (metadata only; not candle integrity)</caption><thead><tr><th>Dataset</th><th>Interval</th><th>Status</th><th>Archives</th><th>First period</th><th>Last period</th></tr></thead>
              <tbody>{coverage.filter(record => coverageStatusFilter === "ALL" || (coverageStatusFilter === "UNKNOWN" ? !["AVAILABLE", "PARTIAL", "UNAVAILABLE"].includes(record.state ?? "") : record.state === coverageStatusFilter)).map((record, index) => ({record, index})).sort((a, b) => incompleteFirst ? Number(b.record.state !== "AVAILABLE") - Number(a.record.state !== "AVAILABLE") : 0).map(({record, index}) => <tr key={`${record.dataset ?? "dataset"}-${record.interval ?? "none"}-${index}`}>
                <td>{record.dataset ?? "Unknown"}</td><td>{record.interval ?? "—"}</td><td>{record.state ?? "Unknown"}</td>
                <td>{typeof record.archive_count === "number" ? record.archive_count : "—"}</td>
                <td>{record.first_period ?? "—"}</td><td>{record.last_period ?? "—"}</td>
              </tr>)}</tbody></table>
          </div>}
        </div>
      </div> : null}
      {section === "Strategy Designer" && connected && capabilities && <div>
        <h3>Strategy lifecycle (read-only)</h3>
        <p>The following stages are intentionally separate. Existing Python engines own evaluation order and trading behavior; this view is guidance, not a new strategy editor.</p>
        <ol aria-label="Strategy evaluation stages">
          <li><strong>Setup detection</strong> — choose the existing signal strategy and direction. No trade is entered merely because a setup exists.</li>
          <li><strong>Candidate selection</strong> — assess structure quality and candidate eligibility, including Fibonacci-specific selection. Selection is distinct from filtering a trade after a signal.</li>
          <li><strong>Entry trigger and confirmation</strong> — apply the configured confirmation and entry scheduling. Actual intrabar fills remain owned by the Python execution engine.</li>
          <li><strong>Entry / Veto / Flip policy</strong> — evaluate existing rule groups after the candidate stage; these do not redefine structural quality.</li>
          <li><strong>Risk &amp; execution</strong> — retain existing stops, targets, position sizing, cost and exit behavior. Editing remains in the desktop application.</li>
        </ol>
        <p role="note">This browser preview does not edit, save or execute a strategy. Rule IDs below come from the existing CSL registry.</p>
        <h3>Authoritative strategy capabilities</h3>
        <p>Read from the existing CSL rule workspace. This browser view does not define or edit strategy semantics.</p>
        <p>Rule grouping: conditions inside a group = {capabilities.strategy.rule_group_model.conditions_inside_group}; groups inside a family = {capabilities.strategy.rule_group_model.groups_inside_family}.</p>
        <h4>Signal strategies</h4>
        <ul>{capabilities.strategy.signal_strategies.map(item => <li key={item.id}><strong>{item.display_name}</strong> <code>{item.id}</code></li>)}</ul>
        <p>Market permissions: {capabilities.strategy.market_permissions.join(", ")}</p>
        <h4>Entry / Veto / Flip evidence</h4>
        <label htmlFor="evidence-filter">Find evidence by name, ID, type or condition</label>
        <input id="evidence-filter" type="search" value={evidenceQuery} onChange={event => setEvidenceQuery(event.target.value)} />
        <p role="status">{Object.entries(capabilities.strategy.indicators).filter(([id, item]) => [id, item.display_name, item.type, ...item.conditions, ...(item.values ?? [])].join(" ").toLowerCase().includes(evidenceQuery.trim().toLowerCase())).length} matching evidence entries</p>
        <table><caption>Authoritative rule evidence registry</caption><thead><tr><th>Evidence</th><th>Type</th><th>Conditions</th><th>Values</th></tr></thead>
          <tbody>{Object.entries(capabilities.strategy.indicators).filter(([id, item]) => [id, item.display_name, item.type, ...item.conditions, ...(item.values ?? [])].join(" ").toLowerCase().includes(evidenceQuery.trim().toLowerCase())).map(([id, item]) => <tr key={id}>
            <td>{item.display_name}<br /><code>{id}</code></td><td>{item.type}</td><td>{item.conditions.join(", ")}</td><td>{item.values?.join(", ") ?? "Numeric"}</td>
          </tr>)}</tbody>
        </table>
      </div>}
      {section === "Research Features" && connected && capabilities && <div>
        <h3>Production feature registry</h3>
        <p>{capabilities.features.length} registered feature providers. Metadata is projected from the existing production registry; calculations remain in Python. Declared datasets below are not exhaustive: some providers also require auxiliary resources resolved by the existing data layer.</p>
        <label htmlFor="feature-filter">Find feature by name, dataset or dependency</label>
        <input id="feature-filter" type="search" value={featureQuery} onChange={event => setFeatureQuery(event.target.value)} />
        <p role="status">{capabilities.features.filter(item => [item.name, ...item.required_datasets, ...item.optional_datasets, ...item.required_features].join(" ").toLowerCase().includes(featureQuery.trim().toLowerCase())).length} matching feature providers</p>
        <table><caption>Authoritative feature providers</caption><thead><tr><th>Feature</th><th>Version</th><th>Declared datasets*</th><th>Dependencies</th><th>Warmup</th></tr></thead>
          <tbody>{capabilities.features.filter(item => [item.name, ...item.required_datasets, ...item.optional_datasets, ...item.required_features].join(" ").toLowerCase().includes(featureQuery.trim().toLowerCase())).map(item => <tr key={item.name}>
            <td><code>{item.name}</code></td><td>{item.version}</td><td>{item.required_datasets.join(", ") || "None declared"}{item.optional_datasets.length ? ` · optional: ${item.optional_datasets.join(", ")}` : ""}</td><td>{item.required_features.join(", ") || "None"}</td><td>{item.warmup_bars} bars</td>
          </tr>)}</tbody>
        </table>
        <p>* DatasetKind declarations only. Auxiliary data resources such as taker-flow and trade-flow inputs are not enumerated here; consult the existing provider and data-layer requirements before executing research.</p>
      </div>}
      {section === "Trade Visualizer" && <div className="connection">
        <p>Open an existing verified run using the existing Python Strategy Visualizer. No backtest or research execution is enabled.</p>
        <label htmlFor="visualizer-run-id">Completed run ID</label>
        <input id="visualizer-run-id" value={visualizerRunId} onChange={e => {++visualizerRequest.current; setVisualizerRunId(e.target.value); setVisualizerUrl(""); setVisualizerError("");}} placeholder="BTCUSDT_4h_…" />
        <button type="button" disabled={!connected} onClick={() => void openVisualizer()}>Prepare visualizer session</button>
        {visualizerError && <p role="alert">{visualizerError}</p>}
        {visualizerUrl && <p><a href={visualizerUrl} target="_blank" rel="noopener noreferrer">Open verified visualizer in a new tab</a>. This link is local and expires when its session is replaced or the server stops.</p>}
      </div>}
      {section === "Risk & Execution" && connected && releaseCapabilities?.execution === true &&
        releaseCapabilities?.configuration_editing === true &&
        <GuardedRunControls enabled={true} token={token}/>}
      {releaseCapabilities?.execution !== true || releaseCapabilities?.configuration_editing !== true ?
        <p>No strategy execution or configuration editing is enabled.</p> : null}
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
