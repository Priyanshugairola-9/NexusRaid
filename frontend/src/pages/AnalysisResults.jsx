import { useMemo, useState } from "react";
import { TimeSeriesChart } from "../components/Charts.jsx";
import FindingList from "../components/FindingList.jsx";
import RiskPanel from "../components/RiskPanel.jsx";
import { DataTable, EmptyState, ErrorMessage, Loading, Panel, Pill, SimpleTable, Tile } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { api } from "../services/api.js";
import { formatDate, formatNumber } from "../utils/format.js";

const TABS = ["Findings", "Anomalies", "Trends", "Domain checks", "Method and plan"];

function DomainPanel({ domain }) {
  return (
    <Panel title="Detected domain" actions={<Pill kind={domain.level}>{domain.level} evidence</Pill>}>
      <div className="stack-sm">
        <p><strong>{domain.title}</strong>{domain.outcome === "partial" && ": only the checks the available columns support were run."}</p>
        <ul>{domain.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        {domain.alternatives.length > 0 && <p className="small muted">Also considered: {domain.alternatives.map((a) => `${a.title} (${a.level})`).join(", ")}.</p>}
        <details><summary className="small">Limitations</summary><ul className="small">{domain.limitations.map((l) => <li key={l}>{l}</li>)}</ul></details>
      </div>
    </Panel>
  );
}

function AnomalySummary({ anomalies, id }) {
  const multi = anomalies.multivariate;
  return (
    <div className="stack">
      <div className="grid-tiles">
        <Tile label="Rows checked" value={formatNumber(anomalies.observations)} />
        <Tile label="Rows flagged" value={formatNumber(anomalies.flagged_rows)} />
        <Tile label="Share flagged" value={`${anomalies.flagged_pct}%`} />
      </div>
      <p className="small muted">{anomalies.note}</p>
      <Panel title="Per-column checks" actions={<a className="btn small" href={`#/datasets/${id}/anomalies`}>Open Anomaly Explorer</a>}>
        <DataTable
          rows={anomalies.univariate.map((u) => ({ ...u, id: u.column }))}
          columns={[
            { key: "column", label: "Column" },
            { key: "method_name", label: "Method", render: (u) => u.method_name || <span className="muted">Skipped</span> },
            { key: "flagged", label: "Flagged", numeric: true },
            { key: "range", label: "Usual range (90%)", sortable: false, render: (u) => (u.normal_range ? `${formatNumber(u.normal_range.p5)} to ${formatNumber(u.normal_range.p95)}` : "–") },
            { key: "reason", label: "Why this method", sortable: false, render: (u) => <span className="small">{u.reason}</span> },
          ]}
        />
      </Panel>
      <Panel title="Row-level check">
        {multi.skipped ? <p>{multi.reason}</p> : (
          <div className="stack-sm">
            <p><strong>{multi.method_name}</strong> flagged {formatNumber(multi.flagged)} of {formatNumber(multi.scored_rows)} rows ({multi.flagged_pct}%).</p>
            <p className="small">{multi.reason}</p>
            <p className="small">{multi.threshold_explanation}</p>
            <ul className="small">{multi.preprocessing.map((s) => <li key={s}>{s}</li>)}</ul>
          </div>
        )}
      </Panel>
      {anomalies.label_validation.available && (
        <Panel title={`Agreement with the '${anomalies.label_validation.label_column}' label`}>
          <div className="grid-tiles">
            {["precision", "recall", "f1", "false_positive_rate"].map((k) => (
              <Tile key={k} label={k.replaceAll("_", " ")} value={formatNumber(anomalies.label_validation.any_method[k], 3)} />
            ))}
          </div>
          <p className="small muted" style={{ marginTop: "0.6rem" }}>{anomalies.label_validation.note}</p>
        </Panel>
      )}
    </div>
  );
}

function Trends({ trends, colors }) {
  const [column, setColumn] = useState(trends.available ? trends.columns[0] : null);
  if (!trends.available) return <Panel title="Trends over time"><p>{trends.reason}</p></Panel>;
  const charts = trends.charts.filter((c) => c.column === column);
  return (
    <div className="stack">
      <p className="muted">{trends.mode_reason}</p>
      <div className="field" style={{ maxWidth: 360 }}>
        <label htmlFor="trend-col">Column</label>
        <select id="trend-col" value={column} onChange={(e) => setColumn(e.target.value)}>
          {trends.columns.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      {charts.map((chart) => {
        const stats = trends.results.find((r) => r.column === chart.column && r.series === chart.series);
        return (
          <Panel key={chart.series} title={chart.series === "all" ? chart.column : `${chart.column}: ${chart.series}`}
            actions={<Pill kind={stats.direction === "stable" ? "info" : "notice"}>{stats.direction}</Pill>}>
            <TimeSeriesChart chart={chart} colors={colors} axisKind={trends.axis_kind} />
            <p className="small muted">
              Change {stats.pct_change === null ? "–" : `${formatNumber(stats.pct_change)}%`}, drift {formatNumber(stats.drift_score)} baseline spreads,
              Kendall tau {stats.kendall_tau} (p = {stats.p_value}), {stats.spikes.length} spike(s), {stats.level_shifts.length} level change(s).
              Red points are values flagged by anomaly detection.
            </p>
          </Panel>
        );
      })}
      {trends.gap_count > 0 && (
        <Panel title={`Gaps in the data (${trends.gap_count})`}>
          <ul>{trends.gaps.slice(0, 10).map((g, i) => <li key={i}>{g.series !== "all" && `${g.series}: `}{formatDate(new Date(g.start).toISOString())} to {formatDate(new Date(g.end).toISOString())} (about {g.missing_points} missing points)</li>)}</ul>
        </Panel>
      )}
      <ul className="small muted">{trends.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
    </div>
  );
}

function DomainChecks({ panel }) {
  if (!panel.available) return <Panel title="Domain checks"><p>No domain was recognised, so only general analysis was run.</p></Panel>;
  return (
    <div className="stack">
      {panel.metrics.length > 0 && (
        <div className="grid-tiles">{panel.metrics.map((m, i) => <Tile key={i} label={m.label} value={`${formatNumber(m.value)}${m.unit || ""}`} />)}</div>
      )}
      <Panel title={`${panel.title}: checks`}>
        <ul>{panel.checks.map((c, i) => <li key={i}><Pill kind={c.status === "ran" ? "ok" : "info"}>{c.status}</Pill> {c.name}{c.detail && <span className="small muted">: {c.detail}</span>}</li>)}</ul>
        {panel.notes.map((n) => <p key={n} className="small muted">{n}</p>)}
      </Panel>
      {panel.tables.map((t, i) => <Panel key={i}><SimpleTable table={t} /></Panel>)}
    </div>
  );
}

function MethodPlan({ results }) {
  const { plan, meta, config } = results;
  return (
    <div className="stack">
      <Panel title="What ran and why">
        <DataTable rows={plan.stages.map((s) => ({ ...s, id: s.stage }))} columns={[
          { key: "stage", label: "Stage" },
          { key: "runs", label: "Ran", render: (s) => (s.runs ? <Pill kind="ok">yes</Pill> : <Pill kind="info">no</Pill>) },
          { key: "reason", label: "Reason", sortable: false },
        ]} />
      </Panel>
      <Panel title="Columns not used as numeric inputs">
        {plan.excluded_columns.length === 0 ? <p>None.</p> : <ul>{plan.excluded_columns.map((e) => <li key={e.column}><strong>{e.column}</strong>: {e.reason}</li>)}</ul>}
      </Panel>
      <Panel title="Settings used">
        <p className="small muted">Run time {meta.total_seconds} s. Change defaults in Settings.</p>
        <pre className="code">{JSON.stringify(config, null, 2)}</pre>
      </Panel>
    </div>
  );
}

export default function AnalysisResults({ id, colors }) {
  const dataset = useAsync(() => api.dataset(id), [id]);
  const results = useAsync(() => api.results(id), [id]);
  const [tab, setTab] = useState(TABS[0]);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const r = results.data?.results;
  const counts = useMemo(() => r?.summary.finding_counts, [r]);

  const rerun = async () => {
    setRunning(true);
    setRunError(null);
    try {
      await api.analyze(id);
      results.reload();
      dataset.reload();
    } catch (err) {
      setRunError(err);
    } finally {
      setRunning(false);
    }
  };

  if (dataset.loading || results.loading) return <Loading />;
  if (dataset.error) return <ErrorMessage error={dataset.error} />;
  if (results.error?.code === "not_analyzed") {
    return (
      <EmptyState title="Not analysed yet" action={<button className="btn primary" onClick={rerun} disabled={running}>{running ? "Analysing…" : "Run analysis"}</button>}>
        {dataset.data.original_filename} has been uploaded but not analysed.
      </EmptyState>
    );
  }
  if (results.error) return <ErrorMessage error={results.error} onRetry={results.reload} />;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>{dataset.data.original_filename}</h1>
          <p className="muted">Analysed {formatDate(results.data.created_at)} in {results.data.duration_seconds} s.</p>
        </div>
        <div className="row">
          <a className="btn" href={`#/datasets/${id}/profile`}>Profile</a>
          <a className="btn" href="#/reports">Reports</a>
          <button className="btn primary" onClick={rerun} disabled={running}>{running ? "Analysing…" : "Re-analyse"}</button>
        </div>
      </div>
      <ErrorMessage error={runError} />
      <Panel title="Summary">
        <div className="stack-sm">
          {r.summary.lines.map((line) => <p key={line}>{line}</p>)}
          <p className="small muted">{r.summary.reminder}</p>
        </div>
      </Panel>
      <div className="grid-2">
        <DomainPanel domain={r.domain} />
        <RiskPanel risk={r.risk} />
      </div>
      <div className="tabs" role="tablist" aria-label="Result sections">
        {TABS.map((name) => (
          <button key={name} role="tab" aria-selected={tab === name} onClick={() => setTab(name)}>
            {name}{name === "Findings" && counts ? ` (${counts.total})` : ""}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "Findings" && <FindingList findings={r.findings} />}
        {tab === "Anomalies" && <AnomalySummary anomalies={r.anomalies} id={id} />}
        {tab === "Trends" && <Trends trends={r.trends} colors={colors} />}
        {tab === "Domain checks" && <DomainChecks panel={r.domain_analysis} />}
        {tab === "Method and plan" && <MethodPlan results={r} />}
      </div>
    </div>
  );
}
