import { useState } from "react";
import { CorrelationGrid, Histogram } from "../components/Charts.jsx";
import { BarList, DataTable, ErrorMessage, Loading, Panel, Pill, Tile } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { api } from "../services/api.js";
import { formatBytes, formatNumber } from "../utils/format.js";

const KIND_LABELS = {
  numeric: "Number", boolean: "Yes/no", datetime: "Date/time", categorical: "Category", identifier: "Identifier",
  text: "Text", constant: "Constant", empty: "Empty",
};

function ColumnDetail({ column, colors }) {
  return (
    <Panel title={`Column: ${column.name}`}>
      <div className="stack-sm">
        <div className="row">
          <Pill kind="info">{KIND_LABELS[column.kind]}</Pill>
          <span className="small">{formatNumber(column.count)} values, {formatNumber(column.missing)} missing ({column.missing_pct}%), {formatNumber(column.unique)} distinct</span>
        </div>
        {column.notes.map((note) => <p key={note} className="small muted">{note}</p>)}
        {column.kind === "numeric" && (
          <>
            <div className="grid-tiles">
              {["mean", "median", "std", "min", "q1", "q3", "max", "skewness"].map((key) => (
                <Tile key={key} label={key === "std" ? "standard deviation" : key === "q1" ? "1st quartile" : key === "q3" ? "3rd quartile" : key} value={formatNumber(column[key])} />
              ))}
            </div>
            {column.histogram && <Histogram histogram={column.histogram} colors={colors} />}
          </>
        )}
        {column.top_values && <BarList items={column.top_values} />}
        {column.top_values && column.other_count > 0 && <p className="small muted">{formatNumber(column.other_count)} rows have other values.</p>}
        {column.kind === "datetime" && (
          <p>From {column.min} to {column.max}. {column.is_sorted ? "Rows are in time order." : "Rows are not in time order."} Median interval: {column.median_interval_seconds !== null ? `${formatNumber(column.median_interval_seconds)} s` : "–"}.</p>
        )}
        {column.examples && <p className="small">Examples: {column.examples.map((e) => <code key={e} style={{ marginRight: 4 }}>{e}</code>)}</p>}
      </div>
    </Panel>
  );
}

export default function DatasetProfile({ id, colors }) {
  const dataset = useAsync(() => api.dataset(id), [id]);
  const profile = useAsync(() => api.profile(id), [id]);
  const [selected, setSelected] = useState(null);
  if (dataset.loading || profile.loading) return <Loading />;
  if (dataset.error || profile.error) return <ErrorMessage error={dataset.error || profile.error} />;
  const p = profile.data;
  const d = dataset.data;
  const column = p.columns.find((c) => c.name === selected) || null;
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>{d.original_filename}</h1>
          <p className="muted">Dataset profile: what each column contains and how clean the data is.</p>
        </div>
        <div className="row">
          {d.latest_analysis && <a className="btn" href={`#/datasets/${id}/results`}>View results</a>}
          <a className="btn primary" href="#/datasets">Back to datasets</a>
        </div>
      </div>
      <div className="grid-tiles">
        <Tile label="Rows" value={formatNumber(p.overview.rows)} />
        <Tile label="Columns" value={formatNumber(p.overview.columns)} />
        <Tile label="File size" value={formatBytes(p.overview.size_bytes)} />
        <Tile label="Missing cells" value={`${p.overview.missing_pct}%`} />
        <Tile label="Duplicate rows" value={formatNumber(p.overview.duplicate_rows)} />
      </div>
      {d.upload_warnings.length > 0 && <div className="alert warning"><ul style={{ margin: 0 }}>{d.upload_warnings.map((w) => <li key={w}>{w}</li>)}</ul></div>}
      <div className="grid-2">
        <Panel title="Data quality">
          <ul className="stack-sm plain-list">
            {p.quality.map((q) => (
              <li key={q.indicator} className="row" style={{ alignItems: "flex-start" }}>
                <Pill kind={q.level === "ok" ? "ok" : q.level === "notice" ? "notice" : "crit"}>{q.level}</Pill>
                <span><strong>{q.indicator}.</strong> {q.message}</span>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title="Time axis">
          {p.time_axis.available ? (
            <p>{p.time_axis.reason} Range: {String(p.time_axis.start)} to {String(p.time_axis.end)}.</p>
          ) : <p>{p.time_axis.reason}</p>}
        </Panel>
      </div>
      <Panel title="Cleaning applied">
        <p className="small muted">{p.cleaning_note}</p>
        {p.cleaning_log.length === 0 ? <p style={{ marginTop: "0.5rem" }}>No conversions were needed.</p> : (
          <ul>
            {p.cleaning_log.map((entry, i) => (
              <li key={i}><strong>{entry.column}</strong>: {entry.action}. {formatNumber(entry.affected_values)} value(s) affected
                {entry.failed_values ? `, ${formatNumber(entry.failed_values)} could not be converted (${entry.failed_examples.join(", ") || "see data"})` : ""}. {entry.effect}</li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel title="Columns" actions={<span className="small muted">Select a row to inspect a column</span>}>
        <DataTable
          caption="Columns"
          rows={p.columns.map((c) => ({ ...c, id: c.name }))}
          onRowClick={(row) => setSelected(row.name)}
          columns={[
            { key: "name", label: "Column" },
            { key: "kind", label: "Type", render: (r) => KIND_LABELS[r.kind] },
            { key: "missing_pct", label: "Missing %", numeric: true },
            { key: "unique", label: "Distinct", numeric: true },
            { key: "mean", label: "Mean", numeric: true },
            { key: "median", label: "Median", numeric: true },
            { key: "min", label: "Min", numeric: true },
            { key: "max", label: "Max", numeric: true },
          ]}
        />
      </Panel>
      {column && <ColumnDetail column={column} colors={colors} />}
      {p.correlations.available && (
        <Panel title="Correlation matrix">
          <p className="small muted">{p.correlations.method_reason} {p.correlations.note}</p>
          <div style={{ marginTop: "0.75rem" }}><CorrelationGrid correlations={p.correlations} /></div>
        </Panel>
      )}
    </div>
  );
}
