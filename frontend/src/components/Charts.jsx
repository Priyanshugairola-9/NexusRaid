import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ComposedChart, Tooltip, XAxis, YAxis } from "recharts";
import { formatNumber, formatTimeAxis } from "../utils/format.js";

function tooltipStyle(colors) {
  return { contentStyle: { background: colors.surface, border: `1px solid ${colors.line}`, color: colors.ink, borderRadius: 6 }, labelStyle: { color: colors.muted } };
}

// Time series with moving average and markers for flagged values.
export function TimeSeriesChart({ chart, colors, axisKind = "datetime", height = 240 }) {
  const points = chart.points;
  const span = points.length ? points[points.length - 1].t - points[0].t : 0;
  const tick = (value) => (axisKind === "datetime" ? formatTimeAxis(value, span) : formatNumber(value));
  const markers = (chart.markers || []).map((m) => ({ t: m.t, flagged: m.v }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={points} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={colors.line} strokeDasharray="3 3" />
        <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={tick} stroke={colors.muted} fontSize={12} />
        <YAxis stroke={colors.muted} fontSize={12} width={56} tickFormatter={(v) => formatNumber(v)} />
        <Tooltip {...tooltipStyle(colors)} labelFormatter={(v) => (axisKind === "datetime" ? new Date(v).toLocaleString() : `Step ${v}`)} formatter={(v, name) => [formatNumber(v), name]} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line type="monotone" dataKey="v" name="value" stroke={colors.accent} dot={false} strokeWidth={1.3} isAnimationActive={false} />
        <Line type="monotone" dataKey="ma" name="moving average" stroke={colors.second} dot={false} strokeWidth={2} isAnimationActive={false} />
        {markers.length > 0 && <Scatter data={markers} dataKey="flagged" name="flagged" fill={colors.crit} isAnimationActive={false} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function Histogram({ histogram, colors, height = 180 }) {
  const data = histogram.counts.map((count, i) => ({
    range: `${formatNumber(histogram.edges[i])}–${formatNumber(histogram.edges[i + 1])}`,
    mid: (histogram.edges[i] + histogram.edges[i + 1]) / 2,
    count,
  }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={colors.line} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="mid" tickFormatter={(v) => formatNumber(v)} stroke={colors.muted} fontSize={11} />
        <YAxis stroke={colors.muted} fontSize={11} width={44} allowDecimals={false} />
        <Tooltip {...tooltipStyle(colors)} labelFormatter={(_, payload) => payload?.[0]?.payload.range || ""} />
        <Bar dataKey="count" name="rows" fill={colors.accent} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

const LIVE_SERIES = [
  { key: "cpu_percent", name: "CPU %", color: "accent" },
  { key: "memory_percent", name: "Memory %", color: "second" },
  { key: "disk_percent", name: "Disk %", color: "third" },
];

export function LiveChart({ samples, colors, height = 260 }) {
  const data = samples.map((s) => ({ ...s, t: new Date(s.timestamp).getTime() }));
  const span = data.length ? data[data.length - 1].t - data[0].t : 0;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={colors.line} strokeDasharray="3 3" />
        <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={(v) => formatTimeAxis(v, span)} stroke={colors.muted} fontSize={12} />
        <YAxis domain={[0, 100]} stroke={colors.muted} fontSize={12} width={40} />
        <Tooltip {...tooltipStyle(colors)} labelFormatter={(v) => new Date(v).toLocaleTimeString()} formatter={(v, name) => [`${formatNumber(v)}%`, name]} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {LIVE_SERIES.map((s) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={colors[s.color]} dot={false} strokeWidth={1.6} isAnimationActive={false} connectNulls />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

// Correlation matrix as a coloured grid: blue = rise together, amber = move oppositely.
export function CorrelationGrid({ correlations }) {
  const { columns, matrix } = correlations;
  const color = (rho) => {
    if (rho === null) return "transparent";
    const alpha = Math.min(1, Math.abs(rho)) * 0.85;
    return rho >= 0 ? `color-mix(in srgb, var(--chart-1) ${alpha * 100}%, transparent)` : `color-mix(in srgb, var(--chart-2) ${alpha * 100}%, transparent)`;
  };
  return (
    <div style={{ overflowX: "auto" }}>
      <div className="heatmap" style={{ gridTemplateColumns: `minmax(7rem, 10rem) repeat(${columns.length}, minmax(2.2rem, 1fr))` }} role="table" aria-label="Correlation matrix">
        <span />
        {columns.map((c) => <span key={c} className="label" title={c} style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", height: "6rem" }}>{c}</span>)}
        {columns.map((row, i) => [
          <span key={`l${row}`} className="label" title={row}>{row}</span>,
          ...matrix[i].map((rho, j) => (
            <span key={`${i}-${j}`} className="cell" style={{ background: color(rho), color: Math.abs(rho || 0) > 0.55 ? "var(--surface)" : "var(--ink)" }} title={`${row} vs ${columns[j]}: ${rho ?? "n/a"}`}>
              {rho === null ? "" : rho.toFixed(2)}
            </span>
          )),
        ])}
      </div>
    </div>
  );
}
