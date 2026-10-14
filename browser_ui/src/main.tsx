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
  const [message, setMessage] = React.useState("Not connected");
  const [runId, setRunId] = React.useState("");
  const [runInfo, setRunInfo] = React.useState<{ run_id?: string; status?: string } | null>(null);
  const [runError, setRunError] = React.useState("");

  async function loadRun() {
    setRunInfo(null);
    setRunError("");
    if (!/^[A-Za-z0-9_-]{1,100}$/.test(runId)) { setRunError("Enter a valid saved run folder ID"); return; }
    try {
      const value = await getReadOnly<{manifest: {run_id?: string; run_status?: string}; summary: unknown}>(`/api/v1/runs/${runId}`, token);
      setRunInfo({run_id: value.manifest.run_id, status: value.manifest.run_status});
    } catch { setRunError("Saved run unavailable or not accessible"); }
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
      {section === "Runs & Results" && connected && <div className="connection">
        <label htmlFor="run-id">Completed run folder ID</label>
        <input id="run-id" value={runId} onChange={e => setRunId(e.target.value)} placeholder="BTCUSDT_4h_…" />
        <button type="button" onClick={() => void loadRun()}>Read completed run</button>
        {runError && <p role="alert">{runError}</p>}
        {runInfo && <div><h3>Verified saved run</h3><p>Run ID: {runInfo.run_id ?? "Unavailable"}</p><p>Status: {runInfo.status ?? "Not specified"}</p></div>}
      </div>}
      {section === "Data Library" && connected ? <div><h3>Available symbols</h3><ul>{symbols.map(symbol => <li key={symbol}>{symbol}</li>)}</ul></div> :
        <p>This section is being migrated. The existing Python engine and desktop application remain authoritative.</p>}
      <p>No strategy execution or configuration editing is enabled.</p>
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
