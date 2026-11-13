import { EmptyState, ErrorMessage, Loading, Panel, Pill, Tile } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { api } from "../services/api.js";
import { DOMAIN_TITLES, formatDate, formatNumber } from "../utils/format.js";

export default function Overview() {
  const { data, error, loading, reload } = useAsync(() => api.overview(), []);
  if (loading) return <Loading />;
  if (error) return <ErrorMessage error={error} onRetry={reload} />;
  const latest = data.latest_analysis;
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="muted">What has been analysed so far, and what the most recent analysis found.</p>
        </div>
        <a className="btn primary" href="#/upload">Upload a dataset</a>
      </div>
      {data.datasets === 0 ? (
        <Panel>
          <EmptyState title="No datasets yet" action={<a className="btn primary" href="#/upload">Upload your first CSV</a>}>
            Upload a CSV file to profile it, detect unusual values and trends, and get explained findings. Sample files are in the repository's samples folder.
          </EmptyState>
        </Panel>
      ) : (
        <>
          <div className="grid-tiles">
            <Tile label="Datasets" value={formatNumber(data.datasets)} />
            <Tile label="Analyses run" value={formatNumber(data.analyses)} />
            <Tile label="Rows flagged (latest analyses)" value={formatNumber(data.total_flagged_rows)} />
          </div>
          {latest && (
            <Panel title="Latest analysis" actions={<a className="btn small" href={`#/datasets/${latest.dataset_id}/results`}>Open results</a>}>
              <div className="stack-sm">
                <p><strong>{latest.dataset}</strong> <span className="muted small">analysed {formatDate(latest.created_at)}</span></p>
                <p>{latest.headline}</p>
                <div className="row">
                  <Pill kind="info">{DOMAIN_TITLES[latest.domain] || latest.domain}</Pill>
                  <span className="small">{formatNumber(latest.flagged_rows)} flagged rows, {latest.finding_count} findings</span>
                  {latest.risk_level ? <Pill kind={latest.risk_level}>Risk: {latest.risk_level}</Pill> : <span className="small muted">No risk score for this kind of data</span>}
                </div>
              </div>
            </Panel>
          )}
          <div className="grid-2">
            <Panel title="Detected domains">
              {Object.keys(data.domain_distribution).length === 0 ? <p className="muted">Run an analysis to see domains.</p> : (
                <ul>
                  {Object.entries(data.domain_distribution).map(([domain, count]) => (
                    <li key={domain}>{DOMAIN_TITLES[domain] || domain}: <span className="num">{count}</span></li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title="Recent activity">
              <ul className="stack-sm plain-list">
                {data.recent_activity.map((item, i) => (
                  <li key={i}>
                    <a href={`#/datasets/${item.dataset_id}/${item.type === "analysis" ? "results" : "profile"}`}>{item.dataset}</a>{" "}
                    <span className="small muted">{item.type === "analysis" ? "analysed" : "uploaded"} {formatDate(item.time)}, {item.detail}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
