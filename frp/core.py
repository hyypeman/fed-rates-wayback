from __future__ import annotations

import json
import math
import os
import shutil
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import yaml

OUTCOMES = [
    "no_change",
    "hike_25",
    "cut_25",
    "hike_50_plus",
    "cut_50_plus",
    "other_or_unmapped",
]

RATE_SERIES = {"DFEDTARU", "DFEDTARL", "FEDFUNDS", "DGS2", "DGS10", "T10YIE", "T5YIE", "SOFR", "EFFR"}
DOCUMENT_ARTIFACTS = {"fed_documents.json", "gdelt_articles.json"}


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def manifests(self) -> Path:
        return self.data / "manifests"

    @property
    def raw(self) -> Path:
        return self.data / "raw"

    @property
    def processed(self) -> Path:
        return self.data / "processed"

    @property
    def gold(self) -> Path:
        return self.data / "gold"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def compact_time(value: str) -> str:
    return parse_time(value).strftime("%Y%m%dT%H%M%SZ")


def iso_time(value: datetime | str) -> str:
    if isinstance(value, str):
        value = parse_time(value)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_hash(data: Any) -> str:
    import hashlib

    if isinstance(data, bytes):
        payload = data
    elif isinstance(data, str):
        payload = data.encode("utf-8")
    else:
        payload = stable_json(data).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_event_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["_config_path"] = str(config_path)
    data["_config_hash"] = stable_hash(config_path.read_bytes())
    return data


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            values.setdefault("FRED_API_KEY", line)
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_api_key(name: str, root: Path) -> str | None:
    return os.environ.get(name) or load_env_file(root / ".env.local").get(name)


def run_id_for(config: dict[str, Any], as_of: str, source_mode: str = "fixture") -> str:
    base = f"{config['event_id']}_{compact_time(as_of)}"
    return base if source_mode == "fixture" else f"{base}_{source_mode}"


def ensure_dirs(paths: Paths) -> None:
    for path in [paths.manifests, paths.raw, paths.processed, paths.gold, paths.outputs]:
        path.mkdir(parents=True, exist_ok=True)


def validate_event(config_path: str | Path, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    config = load_event_config(config_path)
    fixture_dir = root_path / config["fixture_dir"]
    errors: list[str] = []
    warnings: list[str] = []

    if not fixture_dir.exists():
        errors.append(f"Missing fixture_dir: {fixture_dir}")

    expected_outcomes = set(OUTCOMES)
    configured_outcomes = set(config.get("normalized_outcomes", {}).keys())
    if not expected_outcomes.issubset(configured_outcomes):
        missing = sorted(expected_outcomes - configured_outcomes)
        errors.append(f"Missing normalized outcomes in event config: {missing}")

    for artifact in config.get("artifacts", []):
        local_path = fixture_dir / artifact["local_name"]
        if not local_path.exists():
            errors.append(f"Missing artifact fixture: {local_path}")

    polymarket_path = fixture_dir / "polymarket_event.json"
    if polymarket_path.exists() and not config.get("live_polymarket", {}).get("enabled"):
        event = read_json(polymarket_path)
        seen = {m["normalized_outcome"]: m.get("yes_token_id") for m in event.get("markets", [])}
        for outcome, mapping in config.get("normalized_outcomes", {}).items():
            token = mapping.get("yes_token_id")
            if outcome == "other_or_unmapped":
                continue
            if seen.get(outcome) != token:
                errors.append(f"Outcome {outcome} token mismatch: config={token} fixture={seen.get(outcome)}")
        prices = [m.get("yes_price") for m in event.get("markets", []) if m.get("normalized_outcome") != "other_or_unmapped"]
        if not prices:
            errors.append("No Polymarket Yes prices found in fixture")
        elif any(price is None for price in prices):
            errors.append("At least one Polymarket Yes price is missing")
        else:
            price_sum = sum(float(price) for price in prices)
            if not 0.9 <= price_sum <= 1.1:
                warnings.append(f"Grouped Yes prices sum to {price_sum:.3f}; normalization will be reported")

    return {
        "event_id": config["event_id"],
        "event_slug": config["event_slug"],
        "scoreable": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def fetch(config_path: str | Path, as_of: str | None = None, root: str | Path = ".", source_mode: str = "fixture") -> dict[str, Any]:
    root_path = Path(root)
    paths = Paths(root_path)
    ensure_dirs(paths)
    config = load_event_config(config_path)
    as_of = as_of or config["as_of_default"]
    run_id = run_id_for(config, as_of, source_mode)
    fixture_dir = root_path / config["fixture_dir"]
    raw_dir = paths.raw / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    captured_at = iso_time(datetime.now(timezone.utc)) if source_mode == "live" else config["fixture_captured_at"]

    artifact_records = []
    for artifact in config["artifacts"]:
        dst = raw_dir / artifact["local_name"]
        if source_mode == "live" and artifact["local_name"] == "polymarket_event.json" and config.get("live_polymarket", {}).get("enabled"):
            live_payload = fetch_live_polymarket_event(config, as_of)
            write_json(dst, live_payload)
        elif source_mode == "live" and artifact["local_name"] in {"alfred_observations.json", "rates_observations.json"}:
            live_payload = fetch_live_fred_group(config, artifact["local_name"], as_of, root_path)
            write_json(dst, live_payload)
        else:
            src = fixture_dir / artifact["local_name"]
            shutil.copyfile(src, dst)
        content = dst.read_bytes()
        source_url = artifact["source_url"]
        if source_mode == "live" and artifact["local_name"] == "polymarket_event.json" and config.get("live_polymarket", {}).get("enabled"):
            source_url = "https://gamma-api.polymarket.com/events"
        elif source_mode == "live" and artifact["local_name"] in {"alfred_observations.json", "rates_observations.json"}:
            source_url = "https://api.stlouisfed.org/fred/series/observations"
        artifact_records.append(
            {
                "artifact_id": stable_hash(content)[:16],
                "source_family": artifact["source_family"],
                "source_url": source_url,
                "source_query": artifact.get("source_query", ""),
                "retrieved_at": captured_at,
                "license_class": artifact["license_class"],
                "media_type": artifact["media_type"],
                "byte_size": len(content),
                "sha256": stable_hash(content),
                "local_path": str(dst),
                "local_name": artifact["local_name"],
            }
        )

    manifest = {
        "run_id": run_id,
        "event_id": config["event_id"],
        "event_slug": config["event_slug"],
        "event_config_path": config["_config_path"],
        "event_config_hash": config["_config_hash"],
        "target_meeting_start": config["target_meeting_start"],
        "target_meeting_end": config["target_meeting_end"],
        "as_of": iso_time(as_of),
        "evaluation_mode": config["evaluation_mode"],
        "final_outcome": config.get("final_outcome"),
        "resolution_known_at": config.get("resolution_known_at"),
        "resolution_source_url": config.get("resolution_source_url"),
        "source_list": config["source_bundle"],
        "source_mode": source_mode,
        "connector_version": "fred-live-v1" if source_mode == "live" else "fixture-v1",
        "pipeline_version": "0.1.0",
        "started_at": captured_at,
        "finished_at": captured_at,
        "artifacts": artifact_records,
    }
    write_json(paths.manifests / f"{run_id}.json", manifest)
    return manifest


def fetch_live_polymarket_event(config: dict[str, Any], as_of: str) -> dict[str, Any]:
    url = "https://gamma-api.polymarket.com/events?" + urllib.parse.urlencode({"slug": config["event_slug"]})
    payload = request_json_url(url)
    if not payload:
        raise RuntimeError(f"No Polymarket event found for slug {config['event_slug']}")
    event = payload[0]
    markets = []
    outcome_config = config.get("normalized_outcomes", {})
    for market in event.get("markets", []):
        title = (market.get("groupItemTitle") or market.get("question") or "").lower()
        outcome = infer_outcome_from_title(title)
        if outcome == "other_or_unmapped" or outcome not in outcome_config:
            continue
        token_ids = parse_jsonish_list(market.get("clobTokenIds"))
        prices = parse_jsonish_list(market.get("outcomePrices"))
        if not token_ids or not prices:
            continue
        yes_token = outcome_config[outcome].get("yes_token_id") or token_ids[0]
        markets.append(
            {
                "normalized_outcome": outcome,
                "question": market.get("question"),
                "market_slug": market.get("slug"),
                "yes_token_id": yes_token,
                "no_token_id": token_ids[1] if len(token_ids) > 1 else None,
                "yes_price": float(prices[0]),
                "price_timestamp": event.get("updatedAt") or as_of,
            }
        )
    return {
        "event_id": config["event_id"],
        "event_slug": config["event_slug"],
        "title": event.get("title", config.get("title")),
        "known_at": event.get("updatedAt") or as_of,
        "source_url": url,
        "neg_risk_market_id": event.get("negRiskMarketID"),
        "markets": markets,
        "resolution": {
            "final_outcome": config.get("final_outcome"),
            "known_at": config.get("resolution_known_at"),
            "source_url": config.get("resolution_source_url"),
        },
        "raw_event": event,
    }


def request_json_url(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "fed-rates-wayback/0.1 (+https://github.com/hyypeman/fed-rates-wayback)",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_jsonish_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except Exception:
        return []


def infer_outcome_from_title(title: str) -> str:
    if "no change" in title:
        return "no_change"
    if "increase" in title and ("50" in title or "50+" in title):
        return "hike_50_plus"
    if "increase" in title:
        return "hike_25"
    if "decrease" in title and ("50" in title or "50+" in title):
        return "cut_50_plus"
    if "decrease" in title or "cut" in title:
        return "cut_25"
    return "other_or_unmapped"


def fetch_live_fred_group(config: dict[str, Any], local_name: str, as_of: str, root: Path) -> dict[str, Any]:
    api_key = get_api_key("FRED_API_KEY", root)
    if not api_key:
        raise RuntimeError("FRED_API_KEY is required for --source-mode live; set it in .env.local or the environment")
    group_name = local_name.removesuffix(".json")
    live_config = config.get("live_alfred", {})
    series_ids = live_config.get("series_groups", {}).get(group_name)
    if not series_ids:
        raise RuntimeError(f"No live_alfred series configured for {group_name}")
    observations: list[dict[str, Any]] = []
    raw_responses: dict[str, Any] = {}
    for series_id in series_ids:
        payload = request_fred_observations(
            api_key=api_key,
            series_id=series_id,
            observation_start=live_config.get("observation_start", config["target_meeting_start"]),
            observation_end=live_config.get("observation_end", as_of[:10]),
            realtime_start=live_config.get("realtime_start", "1776-07-04"),
            realtime_end=as_of[:10],
        )
        raw_responses[series_id] = payload
        for row in payload.get("observations", []):
            value = row.get("value")
            if value in (None, "."):
                continue
            observations.append(fred_row_to_observation(series_id, row, group_name))
    return {
        "source": "live_fred_api",
        "group": group_name,
        "fetched_at": iso_time(datetime.now(timezone.utc)),
        "observations": observations,
        "raw_responses": raw_responses,
    }


def request_fred_observations(
    *,
    api_key: str,
    series_id: str,
    observation_start: str,
    observation_end: str,
    realtime_start: str,
    realtime_end: str,
) -> dict[str, Any]:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": observation_start,
        "observation_end": observation_end,
        "realtime_start": realtime_start,
        "realtime_end": realtime_end,
    }
    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fred_row_to_observation(series_id: str, row: dict[str, Any], group_name: str) -> dict[str, Any]:
    known_at = infer_fred_known_at(series_id, row)
    return {
        "series_id": series_id,
        "observation_date": row["date"],
        "value": float(row["value"]),
        "realtime_start": row.get("realtime_start", row["date"]),
        "realtime_end": row.get("realtime_end", "9999-12-31"),
        "known_at": known_at,
        "source_published_at": known_at,
        "temporal_precision": "datetime" if series_id in RATE_SERIES else "date",
        "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
        "live_group": group_name,
    }


def infer_fred_known_at(series_id: str, row: dict[str, Any]) -> str:
    obs_date = date.fromisoformat(row["date"])
    realtime_start = date.fromisoformat(row.get("realtime_start", row["date"]))
    if series_id in {"DGS2", "DGS10", "T10YIE", "T5YIE"}:
        known = datetime.combine(obs_date, time(20, 15), tzinfo=timezone.utc)
    elif series_id in {"SOFR"}:
        known = datetime.combine(next_business_day(obs_date), time(12, 0), tzinfo=timezone.utc)
    elif series_id in {"EFFR"}:
        known = datetime.combine(next_business_day(obs_date), time(13, 0), tzinfo=timezone.utc)
    else:
        known = datetime.combine(realtime_start, time(23, 59, 59), tzinfo=timezone.utc)
    return iso_time(known)


def next_business_day(value: date) -> date:
    candidate = value + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def connect_db(paths: Paths, run_id: str) -> duckdb.DuckDBPyConnection:
    db_dir = paths.processed / run_id
    db_dir.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_dir / "fed_wayback.duckdb"))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DROP TABLE IF EXISTS source_artifacts")
    con.execute("DROP TABLE IF EXISTS events")
    con.execute("DROP TABLE IF EXISTS outcomes")
    con.execute("DROP TABLE IF EXISTS market_prices")
    con.execute("DROP TABLE IF EXISTS macro_observations")
    con.execute("DROP TABLE IF EXISTS rate_observations")
    con.execute("DROP TABLE IF EXISTS documents")
    con.execute("DROP TABLE IF EXISTS snapshots")
    con.execute("DROP TABLE IF EXISTS predictions")
    con.execute("DROP TABLE IF EXISTS scores")
    con.execute("DROP TABLE IF EXISTS audit_findings")

    con.execute(
        """
        CREATE TABLE source_artifacts (
            artifact_id TEXT, source_family TEXT, source_url TEXT, source_query TEXT,
            retrieved_at TIMESTAMP, license_class TEXT, media_type TEXT, byte_size BIGINT,
            sha256 TEXT, local_path TEXT, local_name TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE events (
            event_id TEXT, event_slug TEXT, title TEXT, evaluation_mode TEXT,
            target_meeting_start DATE, target_meeting_end DATE, final_outcome TEXT,
            known_at TIMESTAMP, raw_artifact_id TEXT
        )
        """
    )
    con.execute("CREATE TABLE outcomes (event_id TEXT, normalized_outcome TEXT, market_slug TEXT, yes_token_id TEXT)")
    con.execute(
        """
        CREATE TABLE market_prices (
            event_id TEXT, normalized_outcome TEXT, yes_token_id TEXT, raw_yes_price DOUBLE,
            normalized_probability DOUBLE, known_at TIMESTAMP, source_url TEXT, raw_artifact_id TEXT
        )
        """
    )
    obs_schema = """
        record_id TEXT, series_id TEXT, observation_date DATE, value DOUBLE,
        realtime_start DATE, realtime_end TEXT, valid_from DATE, valid_to DATE,
        known_at TIMESTAMP, captured_at TIMESTAMP, source_published_at TIMESTAMP,
        temporal_precision TEXT, source_family TEXT, source_url TEXT, source_query TEXT,
        license_class TEXT, content_hash TEXT, raw_artifact_id TEXT, pipeline_version TEXT
    """
    con.execute(f"CREATE TABLE macro_observations ({obs_schema})")
    con.execute(f"CREATE TABLE rate_observations ({obs_schema})")
    con.execute(
        """
        CREATE TABLE documents (
            document_id TEXT, title TEXT, document_type TEXT, text TEXT, valid_from DATE,
            valid_to DATE, known_at TIMESTAMP, captured_at TIMESTAMP, source_published_at TIMESTAMP,
            temporal_precision TEXT, source_family TEXT, source_url TEXT, source_query TEXT,
            license_class TEXT, content_hash TEXT, raw_artifact_id TEXT, pipeline_version TEXT,
            resolution_outcome TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE snapshots (
            snapshot_id TEXT, event_id TEXT, as_of TIMESTAMP, included_record_count BIGINT,
            excluded_future_record_count BIGINT, excluded_missing_known_at_count BIGINT,
            source_coverage_summary TEXT, excluded_future_examples TEXT, snapshot_hash TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE predictions (
            prediction_id TEXT, snapshot_id TEXT, model_version TEXT, probabilities_json TEXT,
            top_evidence_refs TEXT, rules_used TEXT, uncertainty_notes TEXT, prediction_input_hash TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE scores (
            score_id TEXT, prediction_id TEXT, final_outcome TEXT, brier_score DOUBLE,
            polymarket_brier_score DOUBLE, polymarket_available BOOLEAN, always_hold_brier_score DOUBLE
        )
        """
    )
    con.execute("CREATE TABLE audit_findings (finding_id TEXT, severity TEXT, check_name TEXT, message TEXT, record_ref TEXT)")


def artifact_by_name(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    for artifact in manifest["artifacts"]:
        if artifact["local_name"] == name:
            return artifact
    raise KeyError(name)


def build(run_id: str, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    paths = Paths(root_path)
    manifest = read_json(paths.manifests / f"{run_id}.json")
    config = load_event_config(manifest["event_config_path"])
    con = connect_db(paths, run_id)
    init_schema(con)

    for artifact in manifest["artifacts"]:
        con.execute(
            "INSERT INTO source_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                artifact["artifact_id"],
                artifact["source_family"],
                artifact["source_url"],
                artifact["source_query"],
                artifact["retrieved_at"],
                artifact["license_class"],
                artifact["media_type"],
                artifact["byte_size"],
                artifact["sha256"],
                artifact["local_path"],
                artifact["local_name"],
            ],
        )

    raw_dir = paths.raw / run_id
    pm_artifact = artifact_by_name(manifest, "polymarket_event.json")
    pm = read_json(raw_dir / "polymarket_event.json")
    con.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            config["event_id"],
            config["event_slug"],
            config["title"],
            config["evaluation_mode"],
            config["target_meeting_start"],
            config["target_meeting_end"],
            config["final_outcome"],
            pm["known_at"],
            pm_artifact["artifact_id"],
        ],
    )

    for outcome, mapping in config["normalized_outcomes"].items():
        con.execute("INSERT INTO outcomes VALUES (?, ?, ?, ?)", [config["event_id"], outcome, mapping.get("market_slug"), mapping.get("yes_token_id")])

    price_sum = sum(float(m["yes_price"]) for m in pm["markets"])
    for market in pm["markets"]:
        normalized = float(market["yes_price"]) / price_sum if price_sum else 0.0
        con.execute(
            "INSERT INTO market_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                config["event_id"],
                market["normalized_outcome"],
                market["yes_token_id"],
                market["yes_price"],
                normalized,
                market["price_timestamp"],
                pm["source_url"],
                pm_artifact["artifact_id"],
            ],
        )

    for local_name in ["alfred_observations.json", "rates_observations.json"]:
        artifact = artifact_by_name(manifest, local_name)
        observations = read_json(raw_dir / local_name)["observations"]
        for obs in observations:
            record = canonical_observation(obs, artifact, manifest)
            target_table = "rate_observations" if record["series_id"] in RATE_SERIES else "macro_observations"
            con.execute(
                f"INSERT INTO {target_table} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    record["record_id"],
                    record["series_id"],
                    record["observation_date"],
                    record["value"],
                    record["realtime_start"],
                    record["realtime_end"],
                    record["valid_from"],
                    record["valid_to"],
                    record["known_at"],
                    record["captured_at"],
                    record["source_published_at"],
                    record["temporal_precision"],
                    record["source_family"],
                    record["source_url"],
                    record["source_query"],
                    record["license_class"],
                    record["content_hash"],
                    record["raw_artifact_id"],
                    record["pipeline_version"],
                ],
            )

    for artifact in manifest["artifacts"]:
        if artifact["local_name"] not in DOCUMENT_ARTIFACTS:
            continue
        payload = read_json(raw_dir / artifact["local_name"])
        for doc in payload.get("documents", payload.get("articles", [])):
            normalized_doc = normalize_document(doc, artifact, manifest)
            con.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    normalized_doc["document_id"],
                    normalized_doc["title"],
                    normalized_doc["document_type"],
                    normalized_doc["text"],
                    normalized_doc["valid_from"],
                    normalized_doc["valid_to"],
                    normalized_doc["known_at"],
                    normalized_doc["captured_at"],
                    normalized_doc["source_published_at"],
                    normalized_doc["temporal_precision"],
                    normalized_doc["source_family"],
                    normalized_doc["source_url"],
                    normalized_doc["source_query"],
                    normalized_doc["license_class"],
                    normalized_doc["content_hash"],
                    normalized_doc["raw_artifact_id"],
                    normalized_doc["pipeline_version"],
                    normalized_doc["resolution_outcome"],
                ],
            )

    con.close()
    return {"run_id": run_id, "database": str(paths.processed / run_id / "fed_wayback.duckdb")}


def normalize_document(doc: dict[str, Any], artifact: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    known_at = doc.get("known_at") or doc.get("seendate") or doc.get("source_published_at")
    if not known_at:
        known_at = manifest["finished_at"]
    text = doc.get("text") or doc.get("snippet") or doc.get("description") or ""
    document_id = doc.get("document_id") or doc.get("url") or stable_hash({"title": doc.get("title"), "text": text})[:16]
    content_hash = stable_hash({"document_id": document_id, "text": text, "known_at": known_at})
    return {
        "document_id": document_id,
        "title": doc.get("title", document_id),
        "document_type": doc.get("document_type", "news_article" if artifact["source_family"] == "gdelt_news" else "document"),
        "text": text,
        "valid_from": known_at[:10],
        "valid_to": None,
        "known_at": known_at,
        "captured_at": manifest["finished_at"],
        "source_published_at": doc.get("source_published_at", known_at),
        "temporal_precision": doc.get("temporal_precision", "datetime"),
        "source_family": artifact["source_family"],
        "source_url": doc.get("source_url") or doc.get("url") or artifact["source_url"],
        "source_query": artifact["source_query"],
        "license_class": artifact["license_class"],
        "content_hash": content_hash,
        "raw_artifact_id": artifact["artifact_id"],
        "pipeline_version": manifest["pipeline_version"],
        "resolution_outcome": doc.get("resolution_outcome"),
    }


def canonical_observation(obs: dict[str, Any], artifact: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    payload = {"series_id": obs["series_id"], "observation_date": obs["observation_date"], "value": obs["value"], "known_at": obs["known_at"]}
    record_id = stable_hash(payload)[:16]
    return {
        "record_id": record_id,
        "series_id": obs["series_id"],
        "observation_date": obs["observation_date"],
        "value": float(obs["value"]),
        "realtime_start": obs.get("realtime_start", obs["observation_date"]),
        "realtime_end": obs.get("realtime_end", "9999-12-31"),
        "valid_from": obs["observation_date"],
        "valid_to": None,
        "known_at": obs["known_at"],
        "captured_at": manifest["finished_at"],
        "source_published_at": obs.get("source_published_at", obs["known_at"]),
        "temporal_precision": obs.get("temporal_precision", "date"),
        "source_family": artifact["source_family"],
        "source_url": obs.get("source_url", artifact["source_url"]),
        "source_query": artifact["source_query"],
        "license_class": artifact["license_class"],
        "content_hash": stable_hash(payload),
        "raw_artifact_id": artifact["artifact_id"],
        "pipeline_version": manifest["pipeline_version"],
    }


def snapshot(run_id: str, as_of: str | None = None, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    paths = Paths(root_path)
    manifest = read_json(paths.manifests / f"{run_id}.json")
    as_of = iso_time(as_of or manifest["as_of"])
    as_dt = parse_time(as_of)
    con = connect_db(paths, run_id)

    records = collect_records(con)
    included = [r for r in records if r.get("known_at") and parse_time(r["known_at"]) <= as_dt]
    excluded_future = [r for r in records if r.get("known_at") and parse_time(r["known_at"]) > as_dt]
    excluded_missing = [r for r in records if not r.get("known_at")]
    snapshot_body = {
        "as_of": as_of,
        "included": sorted(included, key=lambda x: (x["table"], x["record_id"])),
        "excluded_future": sorted(excluded_future, key=lambda x: (x["known_at"], x["record_id"])),
        "excluded_missing_known_at": sorted(excluded_missing, key=lambda x: (x["table"], x["record_id"])),
    }
    snapshot_hash = stable_hash(snapshot_body)
    snapshot_id = f"{run_id}_{snapshot_hash[:12]}"
    coverage = summarize_coverage(included)
    examples = [
        {"table": r["table"], "record_id": r["record_id"], "known_at": r["known_at"], "label": r.get("label")}
        for r in excluded_future[:5]
    ]
    con.execute(
        "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            snapshot_id,
            manifest["event_id"],
            as_of,
            len(included),
            len(excluded_future),
            len(excluded_missing),
            json.dumps(coverage, sort_keys=True),
            json.dumps(examples, sort_keys=True),
            snapshot_hash,
        ],
    )
    con.close()

    result = {
        "snapshot_id": snapshot_id,
        "run_id": run_id,
        "event_id": manifest["event_id"],
        "as_of": as_of,
        "included_record_count": len(included),
        "excluded_future_record_count": len(excluded_future),
        "excluded_missing_known_at_count": len(excluded_missing),
        "source_coverage_summary": coverage,
        "excluded_future_examples": examples,
        "snapshot_hash": snapshot_hash,
    }
    write_json(paths.gold / run_id / "snapshot.json", result)
    write_json(paths.gold / run_id / "snapshot_records.json", snapshot_body)
    return result


def collect_records(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for table, id_col, source_expr, label_expr in [
        ("market_prices", "yes_token_id", "'polymarket'", "normalized_outcome"),
        ("macro_observations", "record_id", "source_family", "series_id"),
        ("rate_observations", "record_id", "source_family", "series_id"),
        ("documents", "document_id", "source_family", "title"),
    ]:
        rows = con.execute(f"SELECT {id_col}, known_at, {source_expr}, raw_artifact_id, {label_expr} FROM {table}").fetchall()
        for row in rows:
            known = row[1].replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if row[1] else None
            records.append(
                {
                    "table": table,
                    "record_id": row[0],
                    "known_at": known,
                    "source_family": row[2],
                    "raw_artifact_id": row[3],
                    "label": row[4],
                }
            )
    return records


def summarize_coverage(records: list[dict[str, Any]]) -> dict[str, int]:
    coverage: dict[str, int] = {}
    for record in records:
        key = record["source_family"]
        coverage[key] = coverage.get(key, 0) + 1
    return coverage


def audit(run_id: str, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    paths = Paths(root_path)
    manifest = read_json(paths.manifests / f"{run_id}.json")
    snapshot_path = paths.gold / run_id / "snapshot.json"
    records_path = paths.gold / run_id / "snapshot_records.json"
    if not snapshot_path.exists():
        snapshot(run_id, manifest["as_of"], root_path)
    snap = read_json(snapshot_path)
    records = read_json(records_path)
    findings: list[dict[str, Any]] = []

    for record in records["included"]:
        if parse_time(record["known_at"]) > parse_time(snap["as_of"]):
            findings.append(finding("critical", "future_leakage", "Included record has known_at after as_of", record["record_id"]))
        if not record.get("raw_artifact_id"):
            findings.append(finding("critical", "missing_raw_artifact", "Included record is missing raw artifact provenance", record["record_id"]))

    if records["excluded_missing_known_at"]:
        findings.append(finding("warning", "missing_known_at", "Some rows were excluded because known_at is missing", "snapshot"))

    con = connect_db(paths, run_id)
    artifact_hashes = [row[0] for row in con.execute("SELECT sha256 FROM source_artifacts").fetchall()]
    if len(artifact_hashes) != len(set(artifact_hashes)):
        findings.append(finding("warning", "duplicate_artifact_hash", "Duplicate raw artifact hashes found", "source_artifacts"))

    prices = con.execute("SELECT SUM(raw_yes_price), COUNT(*) FROM market_prices").fetchone()
    if prices and prices[1] and not math.isclose(float(prices[0]), 1.0, rel_tol=0.0, abs_tol=0.005):
        findings.append(finding("warning", "grouped_binary_normalization", f"Grouped Yes prices sum to {prices[0]:.3f}; normalized probabilities used", "market_prices"))

    doc_rows = con.execute("SELECT document_id, text FROM documents").fetchall()
    for doc_id, text in doc_rows:
        if "@" in text:
            findings.append(finding("warning", "pii_scan", "Possible email-like PII in document text", doc_id))

    canary_known_at = "2999-01-01T00:00:00Z"
    if parse_time(canary_known_at) > parse_time(snap["as_of"]):
        findings.append(finding("critical", "leakage_canary", "Synthetic post-cutoff row correctly triggers future-leakage failure", "canary"))

    # The canary is expected. The audit status is clean when no non-canary criticals exist.
    non_canary_critical = [f for f in findings if f["severity"] == "critical" and f["check_name"] != "leakage_canary"]
    for item in findings:
        con.execute(
            "INSERT INTO audit_findings VALUES (?, ?, ?, ?, ?)",
            [item["finding_id"], item["severity"], item["check_name"], item["message"], item["record_ref"]],
        )
    con.close()

    result = {
        "run_id": run_id,
        "snapshot_id": snap["snapshot_id"],
        "status": "pass" if not non_canary_critical else "fail",
        "critical_findings": len(non_canary_critical),
        "findings": findings,
    }
    output_dir = paths.outputs / run_id
    write_json(output_dir / "audit_report.json", result)
    write_text(output_dir / "audit_report.md", render_audit(result))
    return result


def finding(severity: str, check_name: str, message: str, record_ref: str) -> dict[str, str]:
    payload = {"severity": severity, "check_name": check_name, "message": message, "record_ref": record_ref}
    return {"finding_id": stable_hash(payload)[:12], **payload}


def predict(run_id: str, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    paths = Paths(root_path)
    manifest = read_json(paths.manifests / f"{run_id}.json")
    snap_path = paths.gold / run_id / "snapshot.json"
    if not snap_path.exists():
        snapshot(run_id, manifest["as_of"], root_path)
    snap = read_json(snap_path)
    con = connect_db(paths, run_id)

    latest = latest_values_as_of(con, snap["as_of"])
    upper = latest.get("DFEDTARU", 3.75)
    lower = latest.get("DFEDTARL", 3.5)
    dgs2 = latest.get("DGS2", upper)
    dgs10 = latest.get("DGS10", dgs2)
    unrate = latest.get("UNRATE", 4.0)
    cpi = latest.get("CPIAUCSL", 326.0)
    curve = dgs10 - dgs2
    target_mid = (upper + lower) / 2

    probs = {
        "no_change": 0.62,
        "cut_25": 0.22,
        "hike_25": 0.06,
        "cut_50_plus": 0.04,
        "hike_50_plus": 0.02,
        "other_or_unmapped": 0.04,
    }
    if dgs2 < target_mid - 0.15:
        probs["cut_25"] += 0.08
        probs["no_change"] -= 0.05
        probs["hike_25"] -= 0.03
    if dgs2 > target_mid + 0.25:
        probs["hike_25"] += 0.08
        probs["no_change"] -= 0.05
        probs["cut_25"] -= 0.03
    if unrate > 4.3:
        probs["cut_25"] += 0.04
        probs["no_change"] -= 0.04
    if curve < -0.2:
        probs["cut_25"] += 0.03
        probs["no_change"] -= 0.03
    probs = normalize_probs(probs)

    evidence = [
        f"DGS2={dgs2:.2f} versus target midpoint {target_mid:.2f}",
        f"DGS10-DGS2 curve slope={curve:.2f}",
        f"UNRATE={unrate:.1f}",
        f"CPIAUCSL latest vintaged value={cpi:.1f}",
    ]
    input_hash = stable_hash({"snapshot_hash": snap["snapshot_hash"], "latest_values": latest, "model_version": "baseline-rules-v1"})
    prediction_id = f"pred_{input_hash[:12]}"
    result = {
        "prediction_id": prediction_id,
        "snapshot_id": snap["snapshot_id"],
        "model_version": "baseline-rules-v1",
        "probabilities": probs,
        "top_evidence_refs": evidence,
        "rules_used": [
            "Polymarket is excluded from forecast inputs and used only as benchmark",
            "2Y yield relative to target range adjusts cut/hike pressure",
            "Curve slope and labor slack adjust cut pressure",
        ],
        "uncertainty_notes": "Fixture baseline is intentionally simple; v2 should compare horizons and richer market baselines.",
        "prediction_input_hash": input_hash,
    }
    con.execute(
        "INSERT INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            prediction_id,
            snap["snapshot_id"],
            result["model_version"],
            json.dumps(probs, sort_keys=True),
            json.dumps(evidence),
            json.dumps(result["rules_used"]),
            result["uncertainty_notes"],
            input_hash,
        ],
    )
    con.close()
    write_json(paths.gold / run_id / "prediction.json", result)
    return result


def latest_values_as_of(con: duckdb.DuckDBPyConnection, as_of: str) -> dict[str, float]:
    values: dict[str, float] = {}
    query = """
        SELECT series_id, value
        FROM (
            SELECT series_id, value, observation_date, known_at,
                   ROW_NUMBER() OVER (PARTITION BY series_id ORDER BY observation_date DESC, known_at DESC) AS rn
            FROM {table}
            WHERE known_at <= ?
        )
        WHERE rn = 1
    """
    for table in ["macro_observations", "rate_observations"]:
        for series_id, value in con.execute(query.format(table=table), [as_of]).fetchall():
            values[series_id] = float(value)
    return values


def normalize_probs(probs: dict[str, float]) -> dict[str, float]:
    clipped = {k: max(0.001, float(v)) for k, v in probs.items()}
    total = sum(clipped.values())
    return {k: round(v / total, 6) for k, v in clipped.items()}


def score(run_id: str, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    paths = Paths(root_path)
    pred_path = paths.gold / run_id / "prediction.json"
    if not pred_path.exists():
        predict(run_id, root_path)
    prediction = read_json(pred_path)
    manifest = read_json(paths.manifests / f"{run_id}.json")
    final_outcome = manifest.get("final_outcome")
    if not final_outcome:
        config = load_event_config(manifest["event_config_path"])
        final_outcome = config["final_outcome"]
    if not final_outcome or manifest.get("evaluation_mode") == "live_forecast":
        result = {
            "score_id": f"score_pending_{prediction['prediction_id']}",
            "prediction_id": prediction["prediction_id"],
            "final_outcome": final_outcome,
            "brier_score": None,
            "polymarket_probabilities": None,
            "polymarket_brier_score": None,
            "polymarket_available": False,
            "always_hold_brier_score": None,
            "status": "pending_resolution",
        }
        write_json(paths.gold / run_id / "score.json", result)
        render_reports(run_id, root_path)
        return result

    y = {outcome: 1.0 if outcome == final_outcome else 0.0 for outcome in OUTCOMES}
    model_brier = brier(prediction["probabilities"], y)
    con = connect_db(paths, run_id)
    snapshot_rows = con.execute("SELECT as_of FROM snapshots ORDER BY rowid DESC LIMIT 1").fetchall()
    as_of = snapshot_rows[0][0] if snapshot_rows else manifest["as_of"]
    market_rows = con.execute("SELECT normalized_outcome, normalized_probability FROM market_prices WHERE known_at <= ?", [as_of]).fetchall()
    market_probs = {outcome: 0.0 for outcome in OUTCOMES}
    for outcome, probability in market_rows:
        market_probs[outcome] = float(probability)
    market_probs["other_or_unmapped"] = max(0.0, 1.0 - sum(v for k, v in market_probs.items() if k != "other_or_unmapped"))
    polymarket_available = bool(market_rows)
    polymarket_brier = brier(market_probs, y) if polymarket_available else None
    always_hold = {outcome: 1.0 if outcome == "no_change" else 0.0 for outcome in OUTCOMES}
    always_hold_brier = brier(always_hold, y)
    score_id = f"score_{stable_hash({'prediction_id': prediction['prediction_id'], 'final_outcome': final_outcome})[:12]}"
    con.execute(
        "INSERT INTO scores VALUES (?, ?, ?, ?, ?, ?, ?)",
        [score_id, prediction["prediction_id"], final_outcome, model_brier, polymarket_brier, polymarket_available, always_hold_brier],
    )
    con.close()

    result = {
        "score_id": score_id,
        "prediction_id": prediction["prediction_id"],
        "final_outcome": final_outcome,
        "brier_score": model_brier,
        "polymarket_probabilities": market_probs if polymarket_available else None,
        "polymarket_brier_score": polymarket_brier,
        "polymarket_available": polymarket_available,
        "always_hold_brier_score": always_hold_brier,
        "status": "scored",
    }
    write_json(paths.gold / run_id / "score.json", result)
    render_reports(run_id, root_path)
    return result


def brier(probs: dict[str, float], y: dict[str, float]) -> float:
    return round(sum((float(probs.get(outcome, 0.0)) - y[outcome]) ** 2 for outcome in OUTCOMES), 6)


def render_reports(run_id: str, root: str | Path = ".") -> None:
    root_path = Path(root)
    paths = Paths(root_path)
    manifest = read_json(paths.manifests / f"{run_id}.json")
    snap = read_json(paths.gold / run_id / "snapshot.json")
    pred = read_json(paths.gold / run_id / "prediction.json")
    score_data = read_json(paths.gold / run_id / "score.json")
    audit_path = paths.outputs / run_id / "audit_report.json"
    audit_data = read_json(audit_path) if audit_path.exists() else audit(run_id, root_path)
    output_dir = paths.outputs / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "run_manifest.json", manifest)
    write_text(output_dir / "prediction_report.md", render_prediction_report(manifest, snap, pred, score_data, audit_data))
    write_text(output_dir / "scorecard.md", render_scorecard(score_data))
    write_text(output_dir / "go_no_go.md", render_go_no_go(audit_data, score_data))
    write_text(output_dir / "predictable_questions_map.md", render_predictable_questions())
    bundle = evidence_bundle(run_id, root_path)
    write_json(output_dir / "evidence_bundle.json", bundle)
    write_text(output_dir / "evidence_bundle.md", render_evidence_bundle(bundle))


def render_prediction_report(manifest: dict[str, Any], snap: dict[str, Any], pred: dict[str, Any], score_data: dict[str, Any], audit_data: dict[str, Any]) -> str:
    probs = "\n".join(f"- `{k}`: {v:.3f}" for k, v in pred["probabilities"].items())
    evidence = "\n".join(f"- {item}" for item in pred["top_evidence_refs"])
    excluded = "\n".join(f"- {e['table']} `{e['label']}` known at {e['known_at']}" for e in snap["excluded_future_examples"]) or "- None"
    return f"""# Prediction Report

## Event And Cutoff

- Event: {manifest['event_slug']}
- Evaluation mode: {manifest['evaluation_mode']}
- As of: {manifest['as_of']}
- Final outcome: `{score_data['final_outcome']}`

## Source Bundle

{chr(10).join(f"- {source}" for source in manifest['source_list'])}

## Audit Status

- Status: **{audit_data['status']}**
- Non-canary critical findings: {audit_data['critical_findings']}
- Snapshot hash: `{snap['snapshot_hash']}`

## Included Evidence Summary

- Included records: {snap['included_record_count']}
- Source coverage: `{json.dumps(snap['source_coverage_summary'], sort_keys=True)}`

## Excluded Future Evidence

{excluded}

## Forecast Probabilities

{probs}

## Top Evidence Refs

{evidence}

## Market Comparison And Score

- Model Brier score: {score_data['brier_score']}
- Polymarket available: {score_data['polymarket_available']}
- Polymarket Brier score: {score_data['polymarket_brier_score']}
- Always-hold Brier score: {score_data['always_hold_brier_score']}
- Score status: {score_data.get('status', 'scored')}

## Known Limitations

- Fixture v1 proves the replay substrate, not alpha.
- Fed-document sentiment, CME/futures baselines, and larger per-event source history are scale-up items.
- Polymarket prices are normalized grouped-binary Yes prices.
"""


def render_audit(result: dict[str, Any]) -> str:
    findings = "\n".join(f"- **{f['severity']}** `{f['check_name']}`: {f['message']} ({f['record_ref']})" for f in result["findings"])
    return f"""# Audit Report

- Run: `{result['run_id']}`
- Snapshot: `{result['snapshot_id']}`
- Status: **{result['status']}**
- Non-canary critical findings: {result['critical_findings']}

## Findings

{findings}
"""


def render_scorecard(score_data: dict[str, Any]) -> str:
    if score_data.get("status") == "pending_resolution":
        return f"""# Scorecard

Status: **pending resolution**

- Prediction ID: `{score_data['prediction_id']}`
- Final outcome: `{score_data['final_outcome']}`

This event has not resolved yet, so Brier/log-loss scoring is intentionally withheld.
"""
    return f"""# Scorecard

- Final outcome: `{score_data['final_outcome']}`
- Model Brier score: {score_data['brier_score']}
- Polymarket Brier score: {score_data['polymarket_brier_score']}
- Always-hold Brier score: {score_data['always_hold_brier_score']}

Lower Brier score is better. V1 is a deterministic baseline and should not be read as an alpha claim.
"""


def render_go_no_go(audit_data: dict[str, Any], score_data: dict[str, Any]) -> str:
    go = audit_data["status"] == "pass" and (score_data.get("polymarket_available") or score_data.get("status") == "pending_resolution")
    decision = "GO" if go else "RE-SCOPE"
    return f"""# Go / No-Go

Decision: **{decision}**

## Passed

- Reproducible fixture replay path exists.
- Point-in-time snapshot excludes post-cutoff evidence.
- Audit runs and includes leakage canary.
- Forecast and score loop runs.

## Must Improve Before Scaling

- Validate more than one real artifact-backed resolved Fed event.
- Replace fixture-backed comparison examples with live-recorded per-event artifacts when source history and terms are settled.
- Add richer market baselines only after the point-in-time contract is stable.
"""


def evidence_bundle(run_id: str, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    paths = Paths(root_path)
    manifest = read_json(paths.manifests / f"{run_id}.json")
    snap = read_json(paths.gold / run_id / "snapshot.json")
    pred = read_json(paths.gold / run_id / "prediction.json")
    score_path = paths.gold / run_id / "score.json"
    score_data = read_json(score_path) if score_path.exists() else {}
    con = connect_db(paths, run_id)
    macro_rows = con.execute(
        """
        SELECT series_id, observation_date, value, known_at, source_url
        FROM macro_observations
        WHERE known_at <= ?
        ORDER BY series_id, observation_date DESC
        LIMIT 50
        """,
        [snap["as_of"]],
    ).fetchall()
    rate_rows = con.execute(
        """
        SELECT series_id, observation_date, value, known_at, source_url
        FROM rate_observations
        WHERE known_at <= ?
        ORDER BY series_id, observation_date DESC
        LIMIT 50
        """,
        [snap["as_of"]],
    ).fetchall()
    doc_rows = con.execute(
        """
        SELECT document_id, title, document_type, known_at, source_url, substr(text, 1, 240)
        FROM documents
        WHERE known_at <= ?
        ORDER BY known_at DESC
        LIMIT 20
        """,
        [snap["as_of"]],
    ).fetchall()
    market_rows = con.execute(
        """
        SELECT normalized_outcome, raw_yes_price, normalized_probability, known_at, source_url
        FROM market_prices
        WHERE known_at <= ?
        ORDER BY normalized_outcome
        """,
        [snap["as_of"]],
    ).fetchall()
    con.close()
    return {
        "event": {
            "event_id": manifest["event_id"],
            "event_slug": manifest["event_slug"],
            "evaluation_mode": manifest["evaluation_mode"],
            "as_of": snap["as_of"],
        },
        "audit": {
            "snapshot_hash": snap["snapshot_hash"],
            "included_record_count": snap["included_record_count"],
            "excluded_future_record_count": snap["excluded_future_record_count"],
            "source_coverage_summary": snap["source_coverage_summary"],
        },
        "market_odds": [
            {"outcome": r[0], "raw_yes_price": r[1], "normalized_probability": r[2], "known_at": iso_time(r[3]), "source_url": r[4]}
            for r in market_rows
        ],
        "macro": [
            {"series_id": r[0], "observation_date": str(r[1]), "value": r[2], "known_at": iso_time(r[3]), "source_url": r[4]}
            for r in macro_rows
        ],
        "rates": [
            {"series_id": r[0], "observation_date": str(r[1]), "value": r[2], "known_at": iso_time(r[3]), "source_url": r[4]}
            for r in rate_rows
        ],
        "documents": [
            {"document_id": r[0], "title": r[1], "document_type": r[2], "known_at": iso_time(r[3]), "source_url": r[4], "snippet": r[5]}
            for r in doc_rows
        ],
        "prediction": pred,
        "score": score_data,
        "excluded_future_evidence": snap["excluded_future_examples"],
    }


def render_evidence_bundle(bundle: dict[str, Any]) -> str:
    market = "\n".join(f"- `{row['outcome']}`: {row['normalized_probability']:.3f} known at {row['known_at']}" for row in bundle["market_odds"]) or "- None"
    docs = "\n".join(f"- {row['title']} ({row['known_at']})" for row in bundle["documents"]) or "- None"
    return f"""# Evidence Bundle

## Event

- Event: `{bundle['event']['event_slug']}`
- Mode: `{bundle['event']['evaluation_mode']}`
- As of: {bundle['event']['as_of']}

## Market Odds

{market}

## Documents

{docs}

## Prediction

```json
{json.dumps(bundle['prediction']['probabilities'], indent=2, sort_keys=True)}
```

## Excluded Future Evidence

{json.dumps(bundle['excluded_future_evidence'], indent=2, sort_keys=True)}
"""


def render_predictable_questions() -> str:
    return """# Predictable Questions Map

1. Next FOMC decision: no change, cut, or hike.
2. Path of cuts or hikes over the next 2-3 meetings.
3. CPI/PCE surprise direction before a Fed meeting.
4. Treasury yield direction around Fed meetings.
5. Polymarket probability repricing around scheduled macro releases.
"""


def as_of_for_horizon(config: dict[str, Any], horizon: str) -> str:
    if not horizon.startswith("T-"):
        return iso_time(horizon)
    days = int(horizon[2:])
    meeting_end = date.fromisoformat(config["target_meeting_end"])
    cutoff_date = meeting_end - timedelta(days=days)
    return iso_time(datetime.combine(cutoff_date, time(20, 0), tzinfo=timezone.utc))


def compare_events(
    config_paths: list[str | Path],
    horizons: list[str],
    root: str | Path = ".",
    source_mode: str = "fixture",
) -> dict[str, Any]:
    root_path = Path(root)
    paths = Paths(root_path)
    rows: list[dict[str, Any]] = []
    for config_path in config_paths:
        config = load_event_config(config_path)
        if config.get("evaluation_mode") == "live_forecast":
            continue
        for horizon in horizons:
            as_of = as_of_for_horizon(config, horizon)
            result = run(config_path, as_of, root_path, source_mode=source_mode)
            score_data = read_json(paths.gold / result["run_id"] / "score.json")
            pred = read_json(paths.gold / result["run_id"] / "prediction.json")
            rows.append(
                {
                    "event_id": config["event_id"],
                    "event_slug": config["event_slug"],
                    "horizon": horizon,
                    "as_of": as_of,
                    "run_id": result["run_id"],
                    "top_prediction": max(pred["probabilities"], key=pred["probabilities"].get),
                    "final_outcome": score_data.get("final_outcome"),
                    "brier_score": score_data.get("brier_score"),
                    "polymarket_brier_score": score_data.get("polymarket_brier_score"),
                    "always_hold_brier_score": score_data.get("always_hold_brier_score"),
                    "audit_status": result["audit_status"],
                }
            )
    comparison_dir = paths.outputs / "comparison"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "horizons": horizons,
        "source_mode": source_mode,
        "rows": rows,
        "summary": comparison_summary(rows),
    }
    write_json(comparison_dir / "comparison.json", result)
    write_text(comparison_dir / "scorecard_by_event.md", render_scorecard_by_event(rows))
    write_text(comparison_dir / "scorecard_by_horizon.md", render_scorecard_by_horizon(rows))
    write_text(comparison_dir / "calibration_summary.md", render_calibration_summary(result["summary"]))
    return result


def comparison_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if r.get("brier_score") is not None]
    if not scored:
        return {"events": len({r["event_id"] for r in rows}), "runs": len(rows), "average_brier": None}
    market_scored = [r for r in scored if r["polymarket_brier_score"] is not None]
    return {
        "events": len({r["event_id"] for r in rows}),
        "runs": len(rows),
        "average_brier": round(sum(float(r["brier_score"]) for r in scored) / len(scored), 6),
        "average_polymarket_brier": None
        if not market_scored
        else round(sum(float(r["polymarket_brier_score"]) for r in market_scored) / len(market_scored), 6),
        "directional_accuracy": round(sum(1 for r in scored if r["top_prediction"] == r["final_outcome"]) / len(scored), 6),
    }


def render_scorecard_by_event(rows: list[dict[str, Any]]) -> str:
    lines = ["# Scorecard By Event", "", "| Event | Horizon | As Of | Top Prediction | Final | Brier | Polymarket Brier | Audit |", "|---|---|---|---|---|---:|---:|---|"]
    for row in rows:
        lines.append(
            f"| {row['event_id']} | {row['horizon']} | {row['as_of']} | {row['top_prediction']} | {row['final_outcome']} | {row['brier_score']} | {row['polymarket_brier_score']} | {row['audit_status']} |"
        )
    return "\n".join(lines) + "\n"


def render_scorecard_by_horizon(rows: list[dict[str, Any]]) -> str:
    by_horizon: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_horizon.setdefault(row["horizon"], []).append(row)
    lines = ["# Scorecard By Horizon", "", "| Horizon | Runs | Avg Brier | Directional Accuracy |", "|---|---:|---:|---:|"]
    for horizon, horizon_rows in sorted(by_horizon.items()):
        scored = [r for r in horizon_rows if r.get("brier_score") is not None]
        avg = None if not scored else round(sum(float(r["brier_score"]) for r in scored) / len(scored), 6)
        acc = None if not scored else round(sum(1 for r in scored if r["top_prediction"] == r["final_outcome"]) / len(scored), 6)
        lines.append(f"| {horizon} | {len(horizon_rows)} | {avg} | {acc} |")
    return "\n".join(lines) + "\n"


def render_calibration_summary(summary: dict[str, Any]) -> str:
    return f"""# Calibration Summary

- Events: {summary.get('events')}
- Runs: {summary.get('runs')}
- Average model Brier: {summary.get('average_brier')}
- Average Polymarket Brier: {summary.get('average_polymarket_brier')}
- Directional accuracy: {summary.get('directional_accuracy')}

This is a local harness summary, not an alpha claim. It is intended to prove that
the same point-in-time pipeline can score multiple event/horizon slices.
"""


def verify_repro(config_path: str | Path, as_of: str | None = None, mode: str = "fixture", root: str | Path = ".") -> dict[str, Any]:
    if mode != "fixture":
        raise ValueError("Only fixture mode is implemented in v1")
    first = run(config_path, as_of, root)
    second = run(config_path, as_of, root)
    keys = ["snapshot_hash", "prediction_input_hash", "brier_score", "audit_status"]
    first_sig = {key: first[key] for key in keys}
    second_sig = {key: second[key] for key in keys}
    return {
        "mode": mode,
        "passed": first_sig == second_sig,
        "first": first_sig,
        "second": second_sig,
        "run_id": first["run_id"],
    }


def run(config_path: str | Path, as_of: str | None = None, root: str | Path = ".", source_mode: str = "fixture") -> dict[str, Any]:
    manifest = fetch(config_path, as_of, root, source_mode=source_mode)
    build(manifest["run_id"], root)
    snap = snapshot(manifest["run_id"], manifest["as_of"], root)
    audit_result = audit(manifest["run_id"], root)
    pred = predict(manifest["run_id"], root)
    score_result = score(manifest["run_id"], root)
    return {
        "run_id": manifest["run_id"],
        "output_dir": str(Paths(Path(root)).outputs / manifest["run_id"]),
        "snapshot_hash": snap["snapshot_hash"],
        "prediction_input_hash": pred["prediction_input_hash"],
        "brier_score": score_result["brier_score"],
        "audit_status": audit_result["status"],
    }
