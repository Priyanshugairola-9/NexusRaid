from app.services.report_generator import build_anomalies_csv, build_html_report
from helpers import load_sample
from app.services.pipeline import run_analysis


def test_html_report_escapes_user_text_and_includes_disclaimer():
    profile, frame = load_sample("server_metrics_synthetic.csv")
    outcome = run_analysis(profile, frame)
    html = build_html_report({"original_filename": "<script>alert(1)</script>.csv"}, profile, outcome.results,
                             outcome.records)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "not prove" in html


def test_csv_export_neutralises_formulas():
    records = [{"row_number": 1, "deviation": 9.0, "methods": ["iqr"], "columns": ["name"],
                "reasons": ["r"], "values": {"name": "=HYPERLINK(\"http://x\")", "amount": -5}}]
    text = build_anomalies_csv(records)
    assert "'=HYPERLINK" in text
    assert ",-5" in text
