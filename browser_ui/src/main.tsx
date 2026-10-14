import React from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

const sections = ["Data Library", "Runs & Results", "Configurations", "Strategy Designer", "Trade Visualizer"] as const;
type Section = (typeof sections)[number];

function App() {
  const [section, setSection] = React.useState<Section>("Runs & Results");
  return <main className="layout">
    <aside><h1>Crypto Strategy Lab</h1><p>Browser migration · read-only foundation</p>
      <nav aria-label="Research sections">{sections.map(item =>
        <button key={item} type="button" aria-current={section === item ? "page" : undefined} onClick={() => setSection(item)}>{item}</button>
      )}</nav>
    </aside>
    <section aria-live="polite"><header><small>RESEARCH WORKSPACE</small><h2>{section}</h2></header>
      <p>This section is being migrated. The native Python engine and desktop application remain authoritative.</p>
      <p>No strategy execution or configuration editing is enabled in this browser foundation.</p>
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
