from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from frp import core

app = typer.Typer(help="Fed Rate Wayback Machine CLI")


def _print_json(data: dict) -> None:
    import json

    typer.echo(json.dumps(data, indent=2, sort_keys=True))


def _resolve_event_config(event_config: Optional[Path], event_slug: Optional[str]) -> Path:
    if event_config is not None:
        if not event_config.exists():
            raise typer.BadParameter(f"Event config not found: {event_config}")
        return event_config
    if not event_slug:
        raise typer.BadParameter("Provide --event-config or --event-slug")
    for path in sorted(Path("configs/events").glob("*.yaml")):
        config = core.load_event_config(path)
        if config.get("event_slug") == event_slug or config.get("event_id") == event_slug:
            return path
    raise typer.BadParameter(f"No event config found for slug or id: {event_slug}")


@app.command("validate-event")
def validate_event(
    event_config: Optional[Path] = typer.Option(None, "--event-config", help="Path to event YAML config"),
    event_slug: Optional[str] = typer.Option(None, "--event-slug", help="Event slug or event_id from configs/events"),
) -> None:
    """Validate fixture artifacts and Polymarket outcome mapping for an event."""
    event_config = _resolve_event_config(event_config, event_slug)
    result = core.validate_event(event_config)
    _print_json(result)
    if not result["scoreable"]:
        raise typer.Exit(1)


@app.command()
def fetch(
    event_config: Optional[Path] = typer.Option(None, "--event-config"),
    event_slug: Optional[str] = typer.Option(None, "--event-slug"),
    as_of: Optional[str] = typer.Option(None, "--as-of"),
    source_mode: str = typer.Option("fixture", "--source-mode", help="fixture or live"),
) -> None:
    """Copy fixture raw artifacts into the run raw store and write the manifest."""
    event_config = _resolve_event_config(event_config, event_slug)
    _print_json(core.fetch(event_config, as_of, source_mode=source_mode))


@app.command()
def build(run_id: str = typer.Option(..., "--run-id")) -> None:
    """Normalize raw artifacts into DuckDB."""
    _print_json(core.build(run_id))


@app.command()
def snapshot(run_id: str = typer.Option(..., "--run-id"), as_of: Optional[str] = typer.Option(None, "--as-of")) -> None:
    """Materialize the point-in-time snapshot."""
    _print_json(core.snapshot(run_id, as_of))


@app.command()
def audit(run_id: str = typer.Option(..., "--run-id")) -> None:
    """Run provenance, leakage, and quality checks."""
    _print_json(core.audit(run_id))


@app.command()
def predict(run_id: str = typer.Option(..., "--run-id")) -> None:
    """Run the deterministic baseline forecast."""
    _print_json(core.predict(run_id))


@app.command()
def score(run_id: str = typer.Option(..., "--run-id")) -> None:
    """Score prediction against final outcome and market benchmark."""
    _print_json(core.score(run_id))


@app.command()
def run(
    event_config: Optional[Path] = typer.Option(None, "--event-config"),
    event_slug: Optional[str] = typer.Option(None, "--event-slug"),
    as_of: Optional[str] = typer.Option(None, "--as-of"),
    source_mode: str = typer.Option("fixture", "--source-mode", help="fixture or live"),
) -> None:
    """Run the full replay: fetch, build, snapshot, audit, predict, score, report."""
    event_config = _resolve_event_config(event_config, event_slug)
    result = core.run(event_config, as_of, source_mode=source_mode)
    _print_json(result)


@app.command("verify-repro")
def verify_repro(
    event_config: Optional[Path] = typer.Option(None, "--event-config"),
    event_slug: Optional[str] = typer.Option(None, "--event-slug"),
    as_of: Optional[str] = typer.Option(None, "--as-of"),
    mode: str = typer.Option("fixture", "--mode"),
) -> None:
    """Verify deterministic replay from the checked-in fixture bundle."""
    event_config = _resolve_event_config(event_config, event_slug)
    result = core.verify_repro(event_config, as_of, mode)
    _print_json(result)
    if not result["passed"]:
        raise typer.Exit(1)


@app.command()
def evidence(run_id: str = typer.Option(..., "--run-id")) -> None:
    """Print the agent-readable evidence bundle for a run."""
    _print_json(core.evidence_bundle(run_id))


@app.command()
def compare(
    configs_dir: Path = typer.Option(Path("configs/events"), "--configs-dir", exists=True),
    horizons: str = typer.Option("T-30,T-14,T-7,T-3,T-1", "--horizons"),
    source_mode: str = typer.Option("fixture", "--source-mode", help="fixture or live"),
) -> None:
    """Run multiple resolved event configs across multiple horizons."""
    config_paths = sorted(configs_dir.glob("*.yaml"))
    result = core.compare_events(config_paths, [h.strip() for h in horizons.split(",") if h.strip()], source_mode=source_mode)
    _print_json(result["summary"])


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Serve the local evidence API."""
    import uvicorn

    uvicorn.run("frp.api:app", host=host, port=port, reload=False)


@app.command("discover-events")
def discover_events(query: str = typer.Option("fed decision", "--query"), closed: str = typer.Option("true", "--closed"), limit: int = typer.Option(10, "--limit")) -> None:
    """Show configured events available to the local harness."""
    closed_bool = closed.strip().lower() not in {"0", "false", "no", "open"}
    events = []
    for path in sorted(Path("configs/events").glob("*.yaml")):
        config = core.load_event_config(path)
        if closed_bool and config.get("evaluation_mode") == "live_forecast":
            continue
        haystack = f"{config.get('event_id')} {config.get('event_slug')} {config.get('title')}".lower()
        if query.lower() not in haystack and "fed decision" not in query.lower():
            continue
        events.append(
            {
                "event_id": config["event_id"],
                "event_slug": config["event_slug"],
                "config": str(path),
                "evaluation_mode": config["evaluation_mode"],
                "status": "fixture-ready" if config["evaluation_mode"] != "live_forecast" else "live-pending-resolution",
            }
        )
        if len(events) >= limit:
            break
    _print_json(
        {
            "query": query,
            "closed": closed_bool,
            "limit": limit,
            "events": events,
        }
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
