import { useEffect, useState } from "react";
import RowDialog from "../components/RowDialog.jsx";
import { DataTable, EmptyState, ErrorMessage, Loading, Pill } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { api } from "../services/api.js";
import { formatDate } from "../utils/format.js";

const PAGE_SIZE = 50;

export default function AnomalyExplorer({ id }) {
  const results = useAsync(() => api.results(id), [id]);
  const [filters, setFilters] = useState({ column: "", method: "", sort: "deviation", order: "desc", offset: 0 });
  const page = useAsync(() => api.anomalies(id, { ...filters, limit: PAGE_SIZE }), [id, JSON.stringify(filters)]);
  const [record, setRecord] = useState(null);
  useEffect(() => setRecord(null), [filters]);

  if (results.loading) return <Loading />;
  if (results.error) return <ErrorMessage error={results.error} />;
  const anomalies = results.data.results.anomalies;
  const columns = Object.keys(anomalies.column_flag_counts);
  const methods = [...new Set([...anomalies.univariate.filter((u) => u.method).map((u) => u.method), anomalies.multivariate.method].filter(Boolean))];
  const update = (change) => setFilters((f) => ({ ...f, ...change, offset: 0 }));

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Anomaly Explorer</h1>
          <p className="muted">Every flagged row with the reason it was flagged. Select a row to see all of its values.</p>
        </div>
        <a className="btn" href={`#/datasets/${id}/results`}>Back to results</a>
      </div>
      <div className="row">
        <div className="field">
          <label htmlFor="ax-col">Column</label>
          <select id="ax-col" value={filters.column} onChange={(e) => update({ column: e.target.value })}>
            <option value="">All columns</option>
            {columns.map((c) => <option key={c} value={c}>{c} ({anomalies.column_flag_counts[c]})</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="ax-method">Method</label>
          <select id="ax-method" value={filters.method} onChange={(e) => update({ method: e.target.value })}>
            <option value="">All methods</option>
            {methods.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="ax-sort">Sort by</label>
          <select id="ax-sort" value={`${filters.sort}:${filters.order}`} onChange={(e) => { const [sort, order] = e.target.value.split(":"); update({ sort, order }); }}>
            <option value="deviation:desc">Most unusual first</option>
            <option value="row_number:asc">Row number</option>
            <option value="time:asc">Time (oldest first)</option>
            <option value="time:desc">Time (newest first)</option>
          </select>
        </div>
      </div>
      {anomalies.records_capped && <p className="small muted">The {anomalies.stored_records.toLocaleString()} most unusual rows are stored for exploration (of {anomalies.flagged_rows.toLocaleString()} flagged).</p>}
      {page.loading && <Loading />}
      <ErrorMessage error={page.error} />
      {page.data && page.data.total === 0 && <EmptyState title="No flagged rows">Nothing matches these filters.</EmptyState>}
      {page.data && page.data.total > 0 && (
        <>
          <DataTable
            caption="Flagged rows"
            rows={page.data.items.map((item) => ({ ...item, id: item.row_number }))}
            onRowClick={setRecord}
            columns={[
              { key: "row_number", label: "Row", numeric: true, sortable: false },
              ...(page.data.items.some((i) => i.time) ? [{ key: "time", label: "Time", sortable: false, render: (r) => formatDate(r.time) }] : []),
              { key: "deviation", label: "Deviation", numeric: true, sortable: false },
              { key: "columns", label: "Columns", sortable: false, render: (r) => r.columns.join(", ") },
              { key: "methods", label: "Methods", sortable: false, render: (r) => r.methods.map((m) => <Pill key={m} kind="info">{m}</Pill>) },
              { key: "reasons", label: "Main reason", sortable: false, render: (r) => <span className="small">{r.reasons[0]}</span> },
            ]}
          />
          <div className="row spread">
            <span className="small muted">Rows {filters.offset + 1}–{Math.min(filters.offset + PAGE_SIZE, page.data.total)} of {page.data.total}</span>
            <div className="row">
              <button className="btn small" disabled={filters.offset === 0} onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - PAGE_SIZE) }))}>Previous</button>
              <button className="btn small" disabled={filters.offset + PAGE_SIZE >= page.data.total} onClick={() => setFilters((f) => ({ ...f, offset: f.offset + PAGE_SIZE }))}>Next</button>
            </div>
          </div>
        </>
      )}
      <RowDialog record={record} onClose={() => setRecord(null)} />
    </div>
  );
}
