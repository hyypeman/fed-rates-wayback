from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from frp import api as frp_api
from frp import core


ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-04-30T20:00:00Z"


def make_workspace(tmp_path: Path) -> Path:
    for name in ["configs", "fixtures"]:
        shutil.copytree(ROOT / name, tmp_path / name)
    return tmp_path


def test_validate_event_fixture_is_scoreable(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = core.validate_event(workspace / "configs/events/fomc_2026_06.yaml", workspace)
    assert result["scoreable"], result
    assert result["errors"] == []


def test_full_run_creates_reports_and_excludes_future_evidence(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    config = workspace / "configs/events/fomc_2026_06.yaml"
    result = core.run(config, AS_OF, workspace)
    run_id = result["run_id"]
    assert result["audit_status"] == "pass"
    assert result["brier_score"] >= 0

    output_dir = workspace / "outputs" / run_id
    assert (output_dir / "prediction_report.md").exists()
    assert (output_dir / "audit_report.md").exists()
    assert (output_dir / "scorecard.md").exists()
    assert (output_dir / "go_no_go.md").exists()
    assert (output_dir / "predictable_questions_map.md").exists()
    assert (output_dir / "evidence_bundle.json").exists()
    assert (output_dir / "evidence_bundle.md").exists()

    snapshot_records = core.read_json(workspace / "data/gold" / run_id / "snapshot_records.json")
    included_labels = {record["label"] for record in snapshot_records["included"]}
    excluded_labels = {record["label"] for record in snapshot_records["excluded_future"]}
    assert "FOMC Statement - June 17, 2026" not in included_labels
    assert "FOMC Statement - June 17, 2026" in excluded_labels
    assert "Markets expect Fed to stay patient before June meeting" in included_labels
    assert "Fresh inflation data complicates Fed outlook" in excluded_labels

    bundle = core.read_json(output_dir / "evidence_bundle.json")
    assert bundle["event"]["event_id"] == "fomc_2026_06"
    assert any(row["series_id"] == "SOFR" for row in bundle["rates"])
    assert any(row["series_id"] == "EFFR" for row in bundle["rates"])


def test_fixture_repro_is_deterministic(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    config = workspace / "configs/events/fomc_2026_06.yaml"
    result = core.verify_repro(config, AS_OF, "fixture", workspace)
    assert result["passed"], result
    assert result["first"] == result["second"]


def test_compare_events_writes_horizon_scorecards(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = core.compare_events(
        [
            workspace / "configs/events/fomc_2026_06.yaml",
            workspace / "configs/events/fomc_2026_03.yaml",
        ],
        ["T-30", "T-1"],
        workspace,
    )
    assert result["summary"]["events"] == 2
    assert result["summary"]["runs"] == 4
    comparison_dir = workspace / "outputs/comparison"
    assert (comparison_dir / "comparison.json").exists()
    assert (comparison_dir / "scorecard_by_event.md").exists()
    assert (comparison_dir / "scorecard_by_horizon.md").exists()
    assert (comparison_dir / "calibration_summary.md").exists()


def test_live_july_event_validates_without_fixture_token_match(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = core.validate_event(workspace / "configs/events/fomc_2026_07_live.yaml", workspace)
    assert result["scoreable"], result


def test_live_polymarket_fetch_maps_outcomes_with_config_tokens(monkeypatch, tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    config = core.load_event_config(workspace / "configs/events/fomc_2026_07_live.yaml")

    def fake_request_json_url(url: str):
        assert "fed-decision-in-july-181" in url
        return [
            {
                "title": "Fed Decision in July 2026",
                "updatedAt": "2026-06-20T19:00:00Z",
                "negRiskMarketID": "0xlive",
                "markets": [
                    {
                        "groupItemTitle": "No change",
                        "question": "No change in Fed interest rates after July 2026 meeting?",
                        "slug": "will-there-be-no-change-in-fed-interest-rates-after-the-july-2026-meeting",
                        "clobTokenIds": "[\"raw_yes\", \"raw_no\"]",
                        "outcomePrices": "[\"0.82\", \"0.18\"]",
                    }
                ],
            }
        ]

    monkeypatch.setattr(core, "request_json_url", fake_request_json_url)
    payload = core.fetch_live_polymarket_event(config, "2026-06-20T20:00:00Z")
    assert payload["markets"][0]["normalized_outcome"] == "no_change"
    assert payload["markets"][0]["yes_token_id"] == config["normalized_outcomes"]["no_change"]["yes_token_id"]
    assert payload["markets"][0]["yes_price"] == 0.82


def test_api_serves_existing_run(monkeypatch, tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    run_result = core.run(workspace / "configs/events/fomc_2026_06.yaml", AS_OF, workspace)
    monkeypatch.setattr(frp_api, "ROOT", workspace)
    client = TestClient(frp_api.app)

    events = client.get("/events")
    assert events.status_code == 200
    assert any(event["event_id"] == "fomc_2026_06" for event in events.json()["events"])

    evidence = client.get("/evidence", params={"event_id": "fomc_2026_06", "as_of": AS_OF})
    assert evidence.status_code == 200
    assert evidence.json()["prediction"]["model_version"] == "baseline-rules-v1"

    snapshot_id = core.read_json(workspace / "data/gold" / run_result["run_id"] / "snapshot.json")["snapshot_id"]
    snapshot = client.get(f"/snapshot/{snapshot_id}")
    assert snapshot.status_code == 200
    assert snapshot.json()["event_id"] == "fomc_2026_06"
