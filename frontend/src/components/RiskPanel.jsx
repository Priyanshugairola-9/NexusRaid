import { Panel, Pill } from "./ui.jsx";

function Dots({ score }) {
  return (
    <span className="dots" aria-label={`${score} of 3`}>
      {[1, 2, 3].map((n) => <span key={n} className={n <= score ? `on${score}` : ""} />)}
    </span>
  );
}

export default function RiskPanel({ risk }) {
  if (!risk.available) {
    return (
      <Panel title="Risk assessment">
        <p><strong>{risk.message}</strong></p>
        <p className="muted" style={{ marginTop: "0.4rem" }}>{risk.reason}</p>
      </Panel>
    );
  }
  return (
    <Panel title={`Risk assessment: ${risk.title}`} actions={<Pill kind={risk.level}>{risk.level}</Pill>}>
      <div className="stack-sm">
        <p>
          {risk.rules_applied.join(" ")}
          {risk.top_contributors.length > 0 && <> Main contributors: {risk.top_contributors.join(", ")}.</>}
        </p>
        <div>
          {risk.signals.map((signal, i) => (
            <div className="signal" key={i}>
              <strong>{signal.name}</strong>
              <span className="row" style={{ gap: "0.4rem" }}><Dots score={signal.score} /><span className="small muted">×{signal.weight}</span></span>
              <p className="small">{signal.explanation}</p>
            </div>
          ))}
        </div>
        <p className="small muted">{risk.method} {risk.disclaimer}</p>
      </div>
    </Panel>
  );
}
