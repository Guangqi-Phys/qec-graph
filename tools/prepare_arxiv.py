#!/usr/bin/env python3
"""Prepare source, then independently validate it with the downstream parser."""

from __future__ import annotations
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from qecgraph import PARSER_VERSION  # noqa: E402
from qecgraph.source.prepare import (  # noqa: E402
    PREPARE_RULE_VERSION,
    load_source,
    prepare_input,
    parse_prepared,
    recover_output,
    write_outputs,
)


def _check(tree, entry, args):
    handoff = prepare_input(tree, entry)
    return parse_prepared(
        handoff,
        tree,
        recover_parse_errors=not args.no_parser_recovery,
        transparent_containers=not args.no_transparent_containers,
    )


def _normalized_result(candidate, normalized, loading):
    normalized.provenance["loading"] = loading
    candidate.document["source_layer"] = "derived_normalized"
    candidate.document["normalization_status"] = "proposed"
    return replace(candidate, normalization=normalized.provenance)


def _prepare(args):
    loading = []
    local = None
    entry_hint = args.entry
    if args.ai_prepare:
        from qecgraph.source.normalization import load_for_preparation

        tree, loading = load_for_preparation(args.source, repair_legacy_tar=True)
    else:
        tree = load_source(args.source)
    try:
        local = _check(tree, args.entry, args)
        entry_hint = local.entry
        if local.coverage["complete"]:
            if loading:
                local.normalization = {
                    "schema": "qecgraph.preparation_normalization/1",
                    "status": "derived",
                    "loading": loading,
                }
            return local
        diagnostics = json.dumps(
            {"coverage": local.coverage, "diagnostics": local.diagnostics}
        )
    except (ValueError, RuntimeError) as exc:
        diagnostics = str(exc)
    from qecgraph.source.normalization import known_format_plan, apply_plan
    from qecgraph.llm.skills import load_skill

    plan = known_format_plan(tree, entry_hint)
    if plan is not None:
        try:
            normalized = apply_plan(tree, plan, load_skill("prepare_input").schema)
            candidate = _check(normalized.tree, normalized.entry, args)
        except ValueError:
            pass
        else:
            if candidate.coverage["complete"]:
                normalized.provenance["method"] = "deterministic_format_adapter"
                return _normalized_result(candidate, normalized, loading)
    if not args.ai_prepare:
        if local is None:
            raise ValueError(diagnostics)
        return local
    try:
        initial_diagnostics = json.loads(diagnostics)
    except ValueError:
        initial_diagnostics = diagnostics
    from qecgraph.llm.client import LLMClient
    from qecgraph.llm.config import load_ai_config
    from qecgraph.llm.prepare import normalize_input

    config = load_ai_config(args.ai_config_root)
    if args.ai_reasoning_effort is not None:
        if config.selected.kind not in {"openai", "openai_compatible"}:
            raise ValueError(
                "--ai-reasoning-effort requires an OpenAI-compatible provider"
            )
        selected = replace(config.selected, reasoning_effort=args.ai_reasoning_effort)
        config = replace(
            config, providers={**config.providers, config.provider: selected}
        )
    if not config.enabled or not config.allow_source_upload:
        raise ValueError(
            "AI preparation requires enabled AI and explicit source-upload permission"
        )
    client = LLMClient(config, cache_dir=args.out.parent / ".qecgraph-ai-cache")
    # Each proposed format plan is checked by the SAME parser as ordinary input.
    # Failed candidates never replace a prior managed output.
    for attempt in range(1, 3):
        print(f"AI source preparation attempt {attempt}/2", file=sys.stderr)
        try:
            normalized = normalize_input(tree, client, diagnostics, entry=entry_hint)
            candidate = _check(normalized.tree, normalized.entry, args)
        except (ValueError, RuntimeError) as exc:
            from qecgraph.llm.client import BudgetExceeded
            from qecgraph.llm.errors import ProviderError

            if isinstance(exc, (BudgetExceeded, ProviderError)):
                raise
            record = {
                'initial_diagnostics': initial_diagnostics,
                "error": str(exc),
                "rejected_response": getattr(exc, "rejected_response", None),
            }
            folder = args.out.parent / ".qecgraph-preparation-attempts" / tree.digest
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"attempt-{attempt}.json").write_text(
                json.dumps(record, indent=1), encoding="utf-8"
            )
            diagnostics = json.dumps(record)
            continue
        if candidate.coverage["complete"]:
            return _normalized_result(candidate, normalized, loading)
        diagnostics = json.dumps(
            {
                'initial_diagnostics': initial_diagnostics,
                "previous_plan": normalized.provenance["plan"],
                "coverage": candidate.coverage,
                "diagnostics": candidate.diagnostics,
            }
        )
    raise ValueError(
        "Normalized input still fails downstream parsing; previous output retained: "
        + diagnostics[:1000]
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--entry")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--no-parser-recovery", action="store_true")
    parser.add_argument("--no-transparent-containers", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--ai-prepare",
        action="store_true",
        help="request source-format conversion for failed/partial inputs",
    )
    parser.add_argument(
        "--ai-structure",
        dest="ai_prepare",
        action="store_true",
        help="deprecated alias for --ai-prepare; no classifications are generated",
    )
    parser.add_argument("--ai-config-root", type=Path)
    parser.add_argument(
        "--ai-reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high"],
        help="optional provider reasoning override for format conversion",
    )
    args = parser.parse_args(argv)
    if args.recover:
        outcome = recover_output(args.out)
        if outcome == "conflict":
            print(
                f"recovery conflict: {args.out}; backup and journal retained",
                file=sys.stderr,
            )
            return 1
        print(
            json.dumps({"out": str(args.out), "recovered": outcome})
            if args.json
            else f"output {args.out}: {outcome}"
        )
        return 0
    if args.source is None:
        parser.error("source is required unless --recover is used")
    if args.ai_prepare != (args.ai_config_root is not None):
        parser.error("--ai-prepare and --ai-config-root must be supplied together")
    if args.ai_reasoning_effort is not None and not args.ai_prepare:
        parser.error("--ai-reasoning-effort requires --ai-prepare")
    try:
        prepared = _prepare(args)
        write_outputs(
            prepared,
            args.out,
            source=args.source,
            parser_version=PARSER_VERSION,
            prepare_version=PREPARE_RULE_VERSION,
            overwrite=args.overwrite,
            parse_options={
                "recover_parse_errors": not args.no_parser_recovery,
                "transparent_containers": not args.no_transparent_containers,
            },
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"prepare failed: {exc}", file=sys.stderr)
        return 1
    summary = prepared.summary()
    summary.update(
        out=str(args.out),
        preparation={
            "format": "tex",
            "normalized": prepared.normalization is not None,
            "downstream_parse_complete": prepared.coverage["complete"],
        },
    )
    if args.json:
        print(json.dumps(summary, indent=1, ensure_ascii=False))
    else:
        print(f"entry: {summary['entry']} ({summary['entry_bytes']} bytes)")
        print(
            f"blocks: {summary['blocks']} sections: {summary['sections']} output: {args.out}"
        )
    return 0 if prepared.coverage["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
