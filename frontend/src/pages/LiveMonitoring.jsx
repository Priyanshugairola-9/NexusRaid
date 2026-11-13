import { useCallback, useEffect, useState } from "react";
import { LiveChart } from "../components/Charts.jsx";
import FindingList from "../components/FindingList.jsx";
import { EmptyState, ErrorMessage, Loading, Panel, Pill, Tile } from "../components/ui.jsx";
import { api } from "../services/api.js";
import { formatBytes, formatDate, formatNumber } from "../utils/format.js";

const REFRESH_MS = 5000;
const STATE_LABELS = { normal: "Normal", warning: "Warning", critical: "Critical", unknown: "No recent data" };

function useLive(loader, deps, enabled = true) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const load = useCallback(async () => {
    try {
      setState({ data: await loader(), error: null, loading: false });
    } catch (error) {
      setState((s) => ({ ...s, error, loading: false }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    if (!enabled) return undefined;
    load();
    const timer = setInterval(() => document.visibilityState === "visible" && load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load, enabled]);
  return state;
}

function SetupGuide({ ingestionEnabled }) {
  return (
    <Panel title="Connect a computer">
      <div className="stack-sm">
        <p>Live monitoring needs the NexusRaid agent running on the computer you want to watch. A website cannot read your computer by itself; you start the agent yourself and can stop it any time.</p>
        {!ingestionEnabled && <div className="alert warning">Metric ingestion is disabled on this server. Set <code>NEXUSRAID_AGENT_TOKEN</code> in <code>backend/.env</code> and restart the backend.</div>}
        <ol>
          <li>Open a terminal in the <code>monitoring_agent</code> folder and run <code>pip install -r requirements.txt</code>.</li>
          <li>Set the same token as the server: <code>$env:NEXUSRAID_AGENT_TOKEN="your-token"</code> (PowerShell).</li>
          <li>Start it: <code>python agent.py --api-url {window.location.origin}</code></li>
        </ol>
        <p className="small muted">The agent sends CPU, memory, disk and network usage every 15 seconds. Application response times and error counts need instrumentation inside the application and are not collected.</p>
      </div>
    </Panel>
  );
}

function MachineDetail({ machine, colors }) {
  const [minutes, setMinutes] = useState(30);
  const metrics = useLive(() => api.monitoringMetrics(machine.machine_id, minutes), [machine.machine_id, minutes]);
  const alerts = useLive(() => api.monitoringAlerts(machine.machine_id), [machine.machine_id]);
  const [analysis, setAnalysis] = useState(null);
  const [analysing, setAnalysing] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);
  const latest = machine.latest || {};

  const analyse = async () => {
    setAnalysing(true);
    setAnalysisError(null);
    try {
      setAnalysis(await api.monitoringAnalysis(machine.machine_id, 6));
    } catch (err) {
      setAnalysisError(err);
    } finally {
      setAnalysing(false);
    }
  };

  return (
    <div className="stack">
      <div className="grid-tiles">
        <Tile label="CPU" value={latest.cpu_percent != null ? `${formatNumber(latest.cpu_percent)}%` : "–"} />
        <Tile label="Memory" value={latest.memory_percent != null ? `${formatNumber(latest.memory_percent)}%` : "–"} />
        <Tile label="Disk" value={latest.disk_percent != null ? `${formatNumber(latest.disk_percent)}%` : "–"} />
        <Tile label="Network out" value={latest.net_sent_bytes_per_sec != null ? `${formatBytes(latest.net_sent_bytes_per_sec)}/s` : "–"} />
        <Tile label="Network in" value={latest.net_recv_bytes_per_sec != null ? `${formatBytes(latest.net_recv_bytes_per_sec)}/s` : "–"} />
        <Tile label="Processes" value={formatNumber(latest.process_count)} />
      </div>
      <Panel title="Utilisation" actions={
        <div className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.4rem" }}>
          <label htmlFor="live-window">Window</label>
          <select id="live-window" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
            {[15, 30, 60, 180, 720, 1440].map((m) => <option key={m} value={m}>{m < 60 ? `${m} minutes` : `${m / 60} hours`}</option>)}
          </select>
        </div>}>
        {metrics.loading ? <Loading /> : metrics.data?.samples.length ? <LiveChart samples={metrics.data.samples} colors={colors} /> : <p className="muted">No samples in this window.</p>}
        <ErrorMessage error={metrics.error} />
      </Panel>
      <div className="grid-2">
        <Panel title="Alerts">
          {alerts.data?.alerts.length ? (
            <ul className="stack-sm plain-list">
              {alerts.data.alerts.map((a) => (
                <li key={a.id}><Pill kind={a.severity}>{a.severity}</Pill> {a.message} <span className="small muted">{formatDate(a.created_at)}, {a.kind}</span></li>
              ))}
            </ul>
          ) : <p className="muted">No alerts. Repeated alerts are suppressed during the cooldown period unless they get worse.</p>}
        </Panel>
        <Panel title="Analyse recent history" actions={<button className="btn small" onClick={analyse} disabled={analysing}>{analysing ? "Analysing…" : "Analyse last 6 hours"}</button>}>
          <p className="small muted">Runs the same anomaly, trend and risk analysis as for uploaded datasets, on this machine's stored metrics.</p>
          <ErrorMessage error={analysisError} />
          {analysis && (
            <div className="stack-sm" style={{ marginTop: "0.6rem" }}>
              {analysis.summary.lines.map((line) => <p key={line}>{line}</p>)}
              {analysis.risk.available && <p>Risk: <Pill kind={analysis.risk.level}>{analysis.risk.level}</Pill></p>}
            </div>
          )}
        </Panel>
      </div>
      {analysis && <Panel title="Findings from recent history"><FindingList findings={analysis.findings} /></Panel>}
    </div>
  );
}

export default function LiveMonitoring({ colors, info }) {
  const status = useLive(() => api.monitoringStatus(), []);
  const [selected, setSelected] = useState(null);
  if (status.loading) return <Loading />;
  if (status.error && !status.data) return <ErrorMessage error={status.error} />;
  const machines = status.data.machines;
  const machine = machines.find((m) => m.machine_id === selected) || machines[0];
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Live monitoring</h1>
          <p className="muted">Machines running the NexusRaid agent. Refreshes every 5 seconds while this tab is visible.</p>
        </div>
      </div>
      {machines.length === 0 ? (
        <>
          <EmptyState title="No machines connected">Start the monitoring agent on a computer to see live metrics here.</EmptyState>
          <SetupGuide ingestionEnabled={status.data.ingestion_enabled} />
        </>
      ) : (
        <>
          <div className="row">
            {machines.map((m) => (
              <button key={m.machine_id} className="btn" aria-pressed={m.machine_id === machine.machine_id} onClick={() => setSelected(m.machine_id)}
                style={m.machine_id === machine.machine_id ? { borderColor: "var(--accent)" } : undefined}>
                <span className={`status-dot ${m.state}`} aria-hidden="true" /> {m.machine_id}
              </button>
            ))}
          </div>
          <Panel title={machine.machine_id} actions={<Pill kind={machine.state}>{STATE_LABELS[machine.state]}</Pill>}>
            <p className="small">{machine.reasons.map((r) => r.replace(/\.?$/, ".")).join(" ")} Last data {formatDate(machine.last_seen)} ({formatNumber(machine.seconds_since_seen)} s ago), reporting every {machine.interval_seconds} s from {machine.hostname || "unknown host"}.</p>
          </Panel>
          <MachineDetail key={machine.machine_id} machine={machine} colors={colors} />
          <details><summary>How to connect another computer</summary><SetupGuide ingestionEnabled={info.monitoring_ingestion_enabled} /></details>
        </>
      )}
    </div>
  );
}
