from __future__ import annotations

import shutil
from pathlib import Path

from frp import core


ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-04-30T20:00:00Z"


def make_workspace(tmp_path: Path) -> Path:
    for name in ["configs", "fixtures"]:
        shutil.copytree(ROOT / name, tmp_path / name)
    return tmp_path


def test_env_loader_accepts_bare_fred_key(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("abc123\n", encoding="utf-8")
    assert core.load_env_file(env_file)["FRED_API_KEY"] == "abc123"


def test_live_fred_fetch_records_payloads_without_secret(monkeypatch, tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    config = workspace / "configs/events/fomc_2026_06.yaml"
    calls: list[str] = []

    def fake_key(name: str, root: Path) -> str:
        assert name == "FRED_API_KEY"
        return "secret-test-key"

    def fake_request_fred_observations(**kwargs):
        calls.append(kwargs["series_id"])
        return {
            "realtime_start": kwargs["realtime_start"],
            "realtime_end": kwargs["realtime_end"],
            "observation_start": kwargs["observation_start"],
            "observation_end": kwargs["observation_end"],
            "observations": [
                {
                    "realtime_start": "2026-04-01",
                    "realtime_end": "9999-12-31",
                    "date": "2026-03-01",
                    "value": "1.23",
                }
            ],
        }

    monkeypatch.setattr(core, "get_api_key", fake_key)
    monkeypatch.setattr(core, "request_fred_observations", fake_request_fred_observations)

    manifest = core.fetch(config, AS_OF, workspace, source_mode="live")
    run_id = manifest["run_id"]
    assert manifest["source_mode"] == "live"
    assert manifest["connector_version"] == "fred-live-v1"
    assert "secret-test-key" not in core.stable_json(manifest)
    assert any(
        artifact["source_url"] == "https://api.stlouisfed.org/fred/series/observations"
        for artifact in manifest["artifacts"]
        if artifact["local_name"] == "alfred_observations.json"
    )

    raw_text = (workspace / "data/raw" / run_id / "alfred_observations.json").read_text(encoding="utf-8")
    assert "secret-test-key" not in raw_text
    assert "live_fred_api" in raw_text
    assert "raw_responses" in raw_text
    assert {"DFEDTARU", "DFEDTARL", "FEDFUNDS", "UNRATE", "PAYEMS", "CPIAUCSL", "DGS2", "DGS10", "T10YIE", "SOFR", "EFFR"}.issubset(set(calls))


def test_sofr_and_effr_are_known_next_business_day() -> None:
    sofr = core.fred_row_to_observation(
        "SOFR",
        {"date": "2026-04-30", "value": "3.65", "realtime_start": "2026-05-01", "realtime_end": "9999-12-31"},
        "rates_observations",
    )
    effr = core.fred_row_to_observation(
        "EFFR",
        {"date": "2026-05-01", "value": "3.63", "realtime_start": "2026-05-04", "realtime_end": "9999-12-31"},
        "rates_observations",
    )
    assert sofr["known_at"] == "2026-05-01T12:00:00Z"
    assert effr["known_at"] == "2026-05-04T13:00:00Z"
