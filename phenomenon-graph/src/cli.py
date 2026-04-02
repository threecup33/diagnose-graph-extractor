"""CLI entry point for the phenomenon-graph extractor.

Usage:
    python -m src.cli extract <file.txt> --model gpt-4o --api-key sk-...
    python -m src.cli batch <dir/> --model gpt-4o --api-key sk-...
    python -m src.cli merge
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
import yaml

from .extractor import Extractor, LLMConfig
from .graph import MergedGraph
from .schema import PhenomenonGraph

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_GRAPHS_DIR = Path("data/graphs")
DEFAULT_MERGED_OUTPUT = Path("data/merged_graph.json")


def _load_config(config_path: Optional[str]) -> dict:
    """Load YAML config file; return empty dict if not provided or missing."""
    if not config_path:
        return {}
    p = Path(config_path)
    if not p.exists():
        click.echo(f"[warn] Config file not found: {p}", err=True)
        return {}
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _resolve(cli_value, config_dict: dict, key: str, env_var: Optional[str] = None, default=None):
    """Priority: CLI arg > env var > config file > default."""
    if cli_value is not None:
        return cli_value
    if env_var:
        env_value = os.environ.get(env_var)
        if env_value:
            return env_value
    return config_dict.get(key, default)


def _build_llm_config(
    model: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
    extra_headers_json: Optional[str],
    config_dict: dict,
) -> LLMConfig:
    resolved_model = _resolve(model, config_dict, "model")
    resolved_api_key = _resolve(api_key, config_dict, "api_key", env_var="LLM_API_KEY")
    resolved_base_url = _resolve(base_url, config_dict, "base_url", default=DEFAULT_BASE_URL)

    if not resolved_model:
        raise click.UsageError("--model is required (or set 'model' in config.yaml).")
    if not resolved_api_key:
        raise click.UsageError(
            "--api-key is required (or set LLM_API_KEY env var, or 'api_key' in config.yaml)."
        )

    extra_headers: dict = {}
    if extra_headers_json:
        try:
            extra_headers = json.loads(extra_headers_json)
        except json.JSONDecodeError as exc:
            raise click.UsageError(f"--extra-headers must be valid JSON: {exc}") from exc

    return LLMConfig(
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        model=resolved_model,
        extra_headers=extra_headers,
    )


def _default_output_path(input_file: Path) -> Path:
    DEFAULT_GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_GRAPHS_DIR / (input_file.stem + ".json")


def _run_extract(
    input_file: Path,
    llm_config: LLMConfig,
    output: Optional[Path],
) -> Path:
    output_path = output or _default_output_path(input_file)
    text = input_file.read_text(encoding="utf-8")
    extractor = Extractor(llm_config)
    graph = extractor.extract(text, source_file=str(input_file))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(graph.model_dump_json(indent=2))
    return output_path


# ---------------------------------------------------------------------------
# CLI definition
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Phenomenon causal graph extractor for DBA StackExchange posts."""


# Shared options factory
def _common_options(func):
    func = click.option("--model", default=None, help="Model name (e.g. gpt-4o)")(func)
    func = click.option(
        "--api-key", "api_key", default=None,
        help="API key (or set LLM_API_KEY env var)"
    )(func)
    func = click.option(
        "--base-url", "base_url", default=None,
        help=f"Base URL of the OpenAI-compatible API (default: {DEFAULT_BASE_URL})"
    )(func)
    func = click.option(
        "--extra-headers", "extra_headers", default=None,
        help='JSON string of extra HTTP headers, e.g. \'{"anthropic-version":"2023-06-01"}\''
    )(func)
    func = click.option(
        "--config", "config_path", default=None,
        help="Path to config.yaml (default values, overridden by CLI args)"
    )(func)
    return func


@cli.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@_common_options
@click.option("--output", "output", default=None, type=click.Path(path_type=Path),
              help="Output JSON path (default: data/graphs/<name>.json)")
def extract(
    file: Path,
    model: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
    extra_headers: Optional[str],
    config_path: Optional[str],
    output: Optional[Path],
) -> None:
    """Extract a causal graph from a single .txt file."""
    config_dict = _load_config(config_path)
    llm_config = _build_llm_config(model, api_key, base_url, extra_headers, config_dict)

    click.echo(f"Extracting: {file}")
    out = _run_extract(file, llm_config, output)
    click.echo(f"Saved to:   {out}")


@cli.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@_common_options
@click.option("--skip-existing", is_flag=True, default=False,
              help="Skip files that already have a corresponding JSON in data/graphs/")
def batch(
    directory: Path,
    model: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
    extra_headers: Optional[str],
    config_path: Optional[str],
    skip_existing: bool,
) -> None:
    """Batch-extract causal graphs from all .txt files in DIRECTORY."""
    config_dict = _load_config(config_path)
    llm_config = _build_llm_config(model, api_key, base_url, extra_headers, config_dict)

    txt_files = sorted(directory.glob("*.txt"))
    if not txt_files:
        click.echo("No .txt files found in directory.")
        return

    total = len(txt_files)
    success = 0
    skipped = 0

    for i, file in enumerate(txt_files, start=1):
        default_out = _default_output_path(file)
        if skip_existing and default_out.exists():
            click.echo(f"[{i}/{total}] Skipping (already exists): {file.name}")
            skipped += 1
            continue

        click.echo(f"[{i}/{total}] Processing: {file.name}")
        try:
            out = _run_extract(file, llm_config, output=None)
            click.echo(f"          -> Saved: {out}")
            success += 1
        except Exception as exc:
            click.echo(f"          -> ERROR: {exc}", err=True)

    click.echo(f"\nDone. {success} extracted, {skipped} skipped, {total - success - skipped} failed.")


@cli.command()
@click.option("--input-dir", "input_dir", default=str(DEFAULT_GRAPHS_DIR),
              type=click.Path(path_type=Path),
              help=f"Directory with JSON graph files (default: {DEFAULT_GRAPHS_DIR})")
@click.option("--output", "output", default=str(DEFAULT_MERGED_OUTPUT),
              type=click.Path(path_type=Path),
              help=f"Output path for merged graph (default: {DEFAULT_MERGED_OUTPUT})")
def merge(input_dir: Path, output: Path) -> None:
    """Merge all extracted JSON graphs into a single graph and print summary."""
    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        click.echo(f"No JSON files found in {input_dir}.")
        sys.exit(1)

    merged = MergedGraph()
    loaded = 0

    for jf in json_files:
        try:
            with jf.open(encoding="utf-8") as f:
                data = json.load(f)
            graph = PhenomenonGraph(**data)
            merged.add_graph(graph)
            loaded += 1
            click.echo(f"Merged: {jf.name}")
        except Exception as exc:
            click.echo(f"[warn] Skipping {jf.name}: {exc}", err=True)

    if loaded == 0:
        click.echo("No valid graphs to merge.")
        sys.exit(1)

    result = merged.to_dict()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    click.echo(f"\nMerged {loaded} graphs -> {output}")
    click.echo(merged.summary())


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
