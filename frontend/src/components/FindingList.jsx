import { useMemo, useState } from "react";
import { Pill } from "./ui.jsx";

const CATEGORY_LABELS = {
  anomaly: "Unusual values", trend: "Trend", change: "Sudden change", pattern: "Pattern", relationship: "Relationship",
  data_quality: "Data quality", risk: "Risk", validation: "Validation",
};

const SEVERITY_LABELS = { warning: "Needs attention", notice: "Worth a look", info: "For context" };

function Finding({ finding, open, onToggle }) {
  const id = `finding-${finding.id}`;
  return (
    <article className={`finding ${finding.severity}`} data-open={open}>
      <button onClick={onToggle} aria-expanded={open} aria-controls={id}>
        <span className="fid">{finding.id}</span>
        <span>
          <span className="ftitle">{finding.title}</span>
          <span className="fmeta" style={{ display: "block" }}>
            {CATEGORY_LABELS[finding.category] || finding.category}, {SEVERITY_LABELS[finding.severity].toLowerCase()}, {finding.confidence.level} confidence
          </span>
        </span>
        <span className="chev" aria-hidden="true">▸</span>
      </button>
      {open && (
        <dl className="evidence" id={id}>
          <dt>What happened</dt><dd>{finding.what_happened}</dd>
          {finding.columns.length > 0 && (<><dt>Columns</dt><dd>{finding.columns.join(", ")}</dd></>)}
          <dt>Observed</dt><dd>{finding.observed}</dd>
          <dt>Compared with</dt><dd>{finding.comparison}</dd>
          <dt>Why it was flagged</dt><dd>{finding.why_flagged}</dd>
          <dt>Method</dt><dd>{finding.method}</dd>
          <dt>What it could indicate</dt><dd>{finding.could_indicate}</dd>
          <dt>Confidence</dt><dd><Pill kind={finding.confidence.level === "high" ? "ok" : finding.confidence.level === "medium" ? "notice" : "info"}>{finding.confidence.level}</Pill> {finding.confidence.basis}</dd>
          <dt>Information needed</dt><dd>{finding.needs}</dd>
          <dt>Investigate next</dt><dd>{finding.next_steps}</dd>
        </dl>
      )}
    </article>
  );
}

export default function FindingList({ findings }) {
  const [openIds, setOpenIds] = useState(() => new Set(findings.slice(0, 1).map((f) => f.id)));
  const [severity, setSeverity] = useState("all");
  const [category, setCategory] = useState("all");
  const categories = useMemo(() => [...new Set(findings.map((f) => f.category))], [findings]);
  const shown = findings.filter((f) => (severity === "all" || f.severity === severity) && (category === "all" || f.category === category));
  const toggle = (fid) => setOpenIds((current) => {
    const next = new Set(current);
    if (next.has(fid)) next.delete(fid);
    else next.add(fid);
    return next;
  });
  if (!findings.length) return <p className="muted">No findings: nothing in this dataset met the reporting rules.</p>;
  return (
    <div className="stack-sm">
      <div className="row">
        <div className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.4rem" }}>
          <label htmlFor="f-sev">Show</label>
          <select id="f-sev" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="all">All levels</option>
            {Object.entries(SEVERITY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
        </div>
        <div className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.4rem" }}>
          <label htmlFor="f-cat" className="visually-hidden">Category</label>
          <select id="f-cat" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="all">All categories</option>
            {categories.map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c] || c}</option>)}
          </select>
        </div>
        <button className="btn small" onClick={() => setOpenIds(new Set(shown.map((f) => f.id)))}>Expand all</button>
        <button className="btn small" onClick={() => setOpenIds(new Set())}>Collapse all</button>
        <span className="muted small">{shown.length} of {findings.length} shown</span>
      </div>
      {shown.map((finding) => (
        <Finding key={finding.id} finding={finding} open={openIds.has(finding.id)} onToggle={() => toggle(finding.id)} />
      ))}
    </div>
  );
}
