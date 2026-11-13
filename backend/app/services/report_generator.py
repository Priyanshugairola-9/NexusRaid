"""Report generation: a self-contained HTML report and CSV exports.

The HTML report needs no internet connection or extra software: open it in a
browser, and use the browser's Print -> Save as PDF if a PDF is needed.
Everything taken from the dataset is HTML-escaped, because column names and
values are user-controlled text.
"""

import csv
import io
from datetime import datetime, timezone
from html import escape

from app import __version__

MAX_REPORT_RECORDS = 50

STYLE = """
body{font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1f2933;max-width:1000px;margin:24px auto;
padding:0 16px;line-height:1.5}
h1{font-size:26px;margin-bottom:4px}h2{font-size:19px;border-bottom:2px solid #e4e7eb;padding-bottom:4px;
margin-top:32px}h3{font-size:15px;margin:16px 0 4px}.muted{color:#616e7c}.badge{display:inline-block;
padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600}.Low{background:#e3f9e5;color:#1f6f2b}
.Medium{background:#fff3c4;color:#8d6000}.High{background:#ffe3d1;color:#a23b00}.Critical{background:#ffd6d6;
color:#a10000}table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}th,td{border:1px solid
#e4e7eb;padding:4px 6px;text-align:left;vertical-align:top}th{background:#f5f7fa}.finding{border:1px solid
#e4e7eb;border-left:4px solid #2f6fdf;border-radius:4px;padding:8px 12px;margin:10px 0;page-break-inside:avoid}
.finding.warning{border-left-color:#d64545}.finding.notice{border-left-color:#d9a400}dl{display:grid;
grid-template-columns:170px 1fr;gap:2px 10px;margin:6px 0;font-size:13px}dt{font-weight:600;color:#52606d}
dd{margin:0}.box{background:#f5f7fa;border-radius:4px;padding:10px 14px}svg{display:block}
@media print{body{margin:0}h2{page-break-after:avoid}}
"""


def _table(columns: list, rows: list) -> str:
    head = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape('' if cell is None else str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _sparkline(points: list[dict], width: int = 300, height: int = 50) -> str:
    values = [point["v"] for point in points if point.get("v") is not None]
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = width / (len(values) - 1)
    coords = " ".join(
        f"{i * step:.1f},{height - 4 - (value - low) / span * (height - 8):.1f}" for i, value in enumerate(values)
    )
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="trend sparkline"><polyline fill="none" stroke="#2f6fdf" stroke-width="1.5" '
            f'points="{coords}"/></svg>')


def _finding_html(finding: dict) -> str:
    fields = [
        ("What happened", finding["what_happened"]), ("Columns", ", ".join(finding["columns"]) or "-"),
        ("Observed", finding["observed"]), ("Compared with", finding["comparison"]),
        ("Why flagged", finding["why_flagged"]), ("Method", finding["method"]),
        ("Could indicate", finding["could_indicate"]),
        ("Confidence", f"{finding['confidence']['level']} - {finding['confidence']['basis']}"),
        ("Information needed", finding["needs"]), ("Investigate next", finding["next_steps"]),
    ]
    rows = "".join(f"<dt>{escape(label)}</dt><dd>{escape(str(value))}</dd>" for label, value in fields)
    return (f'<div class="finding {escape(finding["severity"])}"><strong>{escape(finding["id"])} · '
            f'{escape(finding["title"])}</strong> <span class="muted">({escape(finding["category"])}, '
            f'{escape(finding["severity"])})</span><dl>{rows}</dl></div>')


def build_html_report(dataset: dict, profile: dict, results: dict, records: list[dict]) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary, domain, risk = results["summary"], results["domain"], results["risk"]
    anomalies, trends = results["anomalies"], results["trends"]
    parts = [
        f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><title>NexusRaid report - "
        f"{escape(dataset['original_filename'])}</title><style>{STYLE}</style></head><body>",
        f"<h1>NexusRaid analysis report</h1><p class='muted'>Dataset: <strong>"
        f"{escape(dataset['original_filename'])}</strong> · {profile['overview']['rows']:,} rows × "
        f"{profile['overview']['columns']} columns · generated {generated} · NexusRaid {__version__}</p>",
        "<h2>Summary</h2><div class='box'>" + "".join(f"<p>{escape(line)}</p>" for line in summary["lines"])
        + f"<p class='muted'>{escape(summary['reminder'])}</p></div>",
    ]

    parts.append("<h2>Detected domain</h2>")
    parts.append(f"<p><strong>{escape(domain['title'])}</strong> - evidence: {escape(domain['level'])}</p>")
    parts.append("<ul>" + "".join(f"<li>{escape(reason)}</li>" for reason in domain["reasons"]) + "</ul>")
    parts.append("<h3>Limitations</h3><ul>" + "".join(f"<li>{escape(item)}</li>" for item in domain["limitations"])
                 + "</ul>")

    parts.append("<h2>Risk assessment</h2>")
    if risk.get("available"):
        parts.append(f"<p>{escape(risk['title'])}: <span class='badge {escape(risk['level'])}'>"
                     f"{escape(risk['level'])}</span> (weighted score ratio {risk['score_ratio']})</p>")
        parts.append(_table(["signal", "score (0-3)", "weight", "explanation"],
                            [[s["name"], s["score"], s["weight"], s["explanation"]] for s in risk["signals"]]))
        parts.append(f"<p class='muted'>{escape(risk['method'])} {escape(risk['disclaimer'])}</p>")
    else:
        parts.append(f"<p><strong>{escape(risk['message'])}</strong> {escape(risk['reason'])}</p>")

    parts.append(f"<h2>Findings ({len(results['findings'])})</h2>")
    parts += [_finding_html(finding) for finding in results["findings"]] or ["<p>No findings.</p>"]

    parts.append("<h2>Anomaly detection</h2>")
    parts.append(f"<p>{anomalies['flagged_rows']:,} of {anomalies['observations']:,} rows flagged "
                 f"({anomalies['flagged_pct']}%) by at least one method.</p>")
    parts.append(_table(
        ["column", "method", "flagged", "normal range (p5-p95)", "why this method"],
        [[u["column"], u.get("method_name") or "skipped", u.get("flagged", "-"),
          f"{u['normal_range']['p5']} - {u['normal_range']['p95']}" if u.get("normal_range") else "-", u["reason"]]
         for u in anomalies["univariate"]]))
    multi = anomalies["multivariate"]
    parts.append(f"<p><strong>Row-level:</strong> "
                 + (escape(multi["reason"]) if multi.get("skipped") else
                    f"{escape(multi['method_name'])}: {multi['flagged']} row(s) flagged. "
                    f"{escape(multi['threshold_explanation'])}") + "</p>")
    if records:
        parts.append(f"<h3>Top {min(len(records), MAX_REPORT_RECORDS)} flagged rows</h3>")
        parts.append(_table(["row", "deviation", "methods", "reasons"],
                            [[r["row_number"], r["deviation"], ", ".join(r["methods"]), " ".join(r["reasons"])]
                             for r in records[:MAX_REPORT_RECORDS]]))

    parts.append("<h2>Trends over time</h2>")
    if trends.get("available"):
        parts.append(f"<p>{escape(trends['mode_reason'])}</p>")
        rows = []
        charts = {(c["series"], c["column"]): c for c in trends.get("charts", [])}
        for item in trends["trend_summary"][:24]:
            chart = charts.get((item["series"], item["column"]))
            rows.append([item["column"], item["series"], item["direction"], item["pct_change"], item["drift_score"],
                         chart])
        parts.append("<table><thead><tr><th>column</th><th>series</th><th>direction</th><th>% change</th>"
                     "<th>drift (spreads)</th><th>shape</th></tr></thead><tbody>")
        for row in rows:
            cells = "".join(f"<td>{escape('' if cell is None else str(cell))}</td>" for cell in row[:5])
            parts.append(f"<tr>{cells}<td>{_sparkline(row[5]['points']) if row[5] else ''}</td></tr>")
        parts.append("</tbody></table>")
    else:
        parts.append(f"<p>{escape(trends['reason'])}</p>")

    parts.append("<h2>Data quality and cleaning</h2>")
    parts.append(_table(["indicator", "level", "detail"],
                        [[q["indicator"], q["level"], q["message"]] for q in profile["quality"]]))
    if profile["cleaning_log"]:
        parts.append(_table(["column", "action", "values affected", "values not converted"],
                            [[c["column"], c["action"], c["affected_values"], c["failed_values"]]
                             for c in profile["cleaning_log"]]))
    parts.append(f"<p class='muted'>{escape(profile['cleaning_note'])}</p>")

    parts.append("<h2>Analysis plan</h2>")
    parts.append(_table(["stage", "ran", "reason"],
                        [[s["stage"], "yes" if s["runs"] else "no", s["reason"]] for s in results["plan"]["stages"]]))
    if results["plan"]["excluded_columns"]:
        parts.append(_table(["excluded column", "kind", "reason"],
                            [[e["column"], e["kind"], e["reason"]] for e in results["plan"]["excluded_columns"]]))

    parts.append("<h2>Disclaimer</h2><p>Anomaly detection identifies statistically unusual data; it does not prove "
                 "that an incident, error, attack or fraud occurred. Risk levels are rule-based indicators, not "
                 "guarantees or probabilities. Results depend on the quality of the input data. Use this report to "
                 "support investigation, not to replace expert judgement.</p></body></html>")
    return "".join(parts)


def _safe_cell(value) -> str:
    """Prevent spreadsheet formula injection: '=cmd()' in a CSV can execute when opened in Excel."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not _is_number(text) else text


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def build_anomalies_csv(records: list[dict]) -> str:
    value_columns: list[str] = []
    for record in records:
        for column in record.get("values", {}):
            if column not in value_columns:
                value_columns.append(column)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["row_number", "time", "deviation", "methods", "flagged_columns", "reasons"] + value_columns)
    for record in records:
        values = record.get("values", {})
        writer.writerow([_safe_cell(cell) for cell in [
            record["row_number"], record.get("time"), record["deviation"], "; ".join(record["methods"]),
            "; ".join(record["columns"]), " | ".join(record["reasons"]),
        ] + [values.get(column) for column in value_columns]])
    return buffer.getvalue()


def build_findings_csv(findings: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    fields = ["id", "severity", "category", "title", "columns", "observed", "comparison", "why_flagged", "method",
              "could_indicate", "confidence", "needs", "next_steps"]
    writer.writerow(fields)
    for finding in findings:
        row = dict(finding, columns="; ".join(finding["columns"]),
                   confidence=f"{finding['confidence']['level']}: {finding['confidence']['basis']}")
        writer.writerow([_safe_cell(row[field]) for field in fields])
    return buffer.getvalue()
