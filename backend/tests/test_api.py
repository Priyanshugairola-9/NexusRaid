"""API tests (need FastAPI installed): run with `pytest` from the backend folder."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.errors import register_error_handlers

API = "/api/v1"


def upload(client, path=None, name="server.csv", content=None):
    data = content if content is not None else path.read_bytes()
    return client.post(f"{API}/datasets/upload", files={"file": (name, data, "text/csv")})


def uploaded_server_dataset(client, samples_dir) -> int:
    response = upload(client, samples_dir / "server_metrics_synthetic.csv")
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_health(client):
    body = client.get(f"{API}/health").json()
    assert body["status"] == "ok" and body["database"] == "ok" and body["storage"] == "ok"


def test_info_is_public_and_lists_limits(client):
    body = client.get(f"{API}/info").json()
    assert body["limits"]["max_upload_mb"] == 2
    assert body["access_key_required"] is False
    assert {domain["domain"] for domain in body["domains"]} >= {"server", "student"}


def test_upload_profile_list(client, samples_dir):
    dataset_id = uploaded_server_dataset(client, samples_dir)
    dataset = client.get(f"{API}/datasets/{dataset_id}").json()
    assert dataset["row_count"] == 864 and dataset["latest_analysis"] is None
    profile = client.get(f"{API}/datasets/{dataset_id}/profile").json()
    assert profile["time_axis"]["column"] == "timestamp"
    assert any(item["id"] == dataset_id for item in client.get(f"{API}/datasets").json())


def test_invalid_uploads_are_rejected_and_not_kept(client):
    upload_dir = get_settings().upload_dir
    before = set(upload_dir.iterdir())
    empty = upload(client, name="empty.csv", content=b"")
    assert empty.status_code == 400 and empty.json()["error"]["code"] == "empty_file"
    wrong_type = upload(client, name="data.txt", content=b"a,b\n1,2\n")
    assert wrong_type.status_code == 415
    too_big = upload(client, name="big.csv", content=b"a,b\n" + b"1,2\n" * 600_000)
    assert too_big.status_code == 413 and too_big.json()["error"]["code"] == "file_too_large"
    assert set(upload_dir.iterdir()) == before


def test_path_tricks_in_file_names_are_neutralised(client):
    response = upload(client, name="../../evil.csv", content=b"a,b\n1,2\n3,4\n")
    assert response.status_code == 201
    assert response.json()["original_filename"] == "evil.csv"


def test_full_analysis_flow(client, samples_dir):
    dataset_id = uploaded_server_dataset(client, samples_dir)
    assert client.get(f"{API}/datasets/{dataset_id}/results").json()["error"]["code"] == "not_analyzed"

    response = client.post(f"{API}/datasets/{dataset_id}/analyze")
    assert response.status_code == 201, response.text
    results = response.json()["results"]
    assert results["domain"]["detected"] == "server"
    assert results["risk"]["level"] == "High"

    assert client.get(f"{API}/datasets/{dataset_id}/results").json()["results"]["summary"]["lines"]

    page = client.get(f"{API}/datasets/{dataset_id}/anomalies", params={"limit": 5}).json()
    assert page["total"] >= 5 and len(page["items"]) == 5
    deviations = [item["deviation"] for item in page["items"]]
    assert deviations == sorted(deviations, reverse=True)
    cpu_only = client.get(f"{API}/datasets/{dataset_id}/anomalies", params={"column": "cpu_usage"}).json()
    assert all("cpu_usage" in item["columns"] for item in cpu_only["items"])
    assert client.get(f"{API}/datasets/{dataset_id}/anomalies", params={"sort": "bad"}).status_code == 422

    report = client.get(f"{API}/datasets/{dataset_id}/report")
    assert report.status_code == 200 and "NexusRaid analysis report" in report.text
    assert "attachment" in report.headers["content-disposition"]
    assert client.get(f"{API}/datasets/{dataset_id}/report", params={"format": "json"}).json()["results"]
    assert client.get(f"{API}/datasets/{dataset_id}/anomalies.csv").text.startswith("row_number")
    assert client.get(f"{API}/datasets/{dataset_id}/findings.csv").text.startswith("id,severity")

    overview = client.get(f"{API}/overview").json()
    assert overview["datasets"] >= 1 and overview["analyses"] >= 1


def test_invalid_analysis_config_is_rejected(client, samples_dir):
    dataset_id = uploaded_server_dataset(client, samples_dir)
    response = client.post(f"{API}/datasets/{dataset_id}/analyze", json={"config": {"iqr_multiplier": 99}})
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_config"


def test_settings_round_trip(client):
    saved = client.put(f"{API}/settings/analysis", json={"config": {"zscore_threshold": 4.0}})
    assert saved.status_code == 200 and saved.json()["config"]["zscore_threshold"] == 4.0
    assert client.get(f"{API}/settings/analysis").json()["config"]["zscore_threshold"] == 4.0
    assert client.put(f"{API}/settings/analysis", json={"config": {"unknown": 1}}).status_code == 422
    client.put(f"{API}/settings/analysis", json={"config": {}})


def test_delete_removes_record_and_file(client, samples_dir):
    dataset_id = uploaded_server_dataset(client, samples_dir)
    files_before = len(list(get_settings().upload_dir.iterdir()))
    assert client.delete(f"{API}/datasets/{dataset_id}").status_code == 204
    assert client.get(f"{API}/datasets/{dataset_id}").status_code == 404
    assert len(list(get_settings().upload_dir.iterdir())) == files_before - 1


def test_unknown_dataset_and_route_use_standard_errors(client):
    assert client.get(f"{API}/datasets/999999").json()["error"]["code"] == "dataset_not_found"
    assert client.get(f"{API}/nope").json()["error"]["code"] == "http_404"


def test_access_key_protects_data_endpoints(client):
    settings = get_settings()
    settings.access_key = "secret-key"
    try:
        assert client.get(f"{API}/datasets").status_code == 401
        assert client.get(f"{API}/datasets", headers={"X-Access-Key": "wrong"}).status_code == 401
        assert client.get(f"{API}/datasets", headers={"X-Access-Key": "secret-key"}).status_code == 200
        assert client.get(f"{API}/info").json()["access_key_required"] is True
        assert client.get(f"{API}/health").status_code == 200
    finally:
        settings.access_key = ""


def test_cors(client):
    allowed = client.options(f"{API}/health", headers={"Origin": "http://localhost:5173",
                                                       "Access-Control-Request-Method": "GET"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    denied = client.options(f"{API}/health", headers={"Origin": "http://evil.example",
                                                      "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in denied.headers


def test_security_headers(client):
    headers = client.get(f"{API}/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"


def test_unexpected_errors_hide_internal_details():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/crash")
    def crash():
        raise RuntimeError("secret internal detail")

    response = TestClient(app, raise_server_exceptions=False).get("/crash")
    assert response.status_code == 500
    assert "secret" not in response.text
