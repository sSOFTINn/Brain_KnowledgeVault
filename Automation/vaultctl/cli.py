from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

from .ask import ask, ask_as_markdown
from .config import discover_config_path, load_config
from .backup import (
    backup_check,
    backup_init,
    backup_preflight,
    backup_restore_drill,
    backup_run,
    backup_snapshots,
)
from .codex_storage import audit_codex_storage, create_codex_cleanup_plan
from .doctor import checks_as_dict, has_failures, run_doctor
from .event_log import record_command
from .migrator import (
    approve_migration_row,
    effective_migration_plan,
    execute_migration_plan,
    is_migration_plan,
)
from .indexer import integrity_check, rebuild_index, search_index
from .extractor import rebuild_extractions
from .graph import build_graph, export_graph, graph_neighbors, graph_stats
from .operations import create_cleanup_plan, generate_report, verify_run
from .planner import create_plan
from .rag.store import query_sources, rebuild_rag, write_sources_report
from .router import approve_route, create_run, effective_plan, execute_plan, inventory
from .scanner import scan
from .scaffold import initialize
from .storage import audit_storage, bootstrap_storage, marker_path
from .repositories import (
    apply_repository_plan,
    approve_repository,
    create_repository_plan,
    effective_repository_plan,
    verify_repository_plan,
)
from .suggestions import generate_suggestions
from .validator import findings_as_dict, has_errors, validate_vault
from .wiki import apply_draft, approve_draft, draft_concept, draft_moc, suggest_links, summarize_path
from .windows_profile import audit_windows_profile


def _add_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config")
    parser.add_argument("--root", help="Override KnowledgeVault root")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vaultctl", description="KnowledgeVault control plane")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create the KnowledgeVault skeleton")
    _add_config(init)
    init.add_argument("--dry-run", action="store_true")
    init.add_argument("--force-template-update", action="store_true")

    bootstrap = subparsers.add_parser(
        "bootstrap", help="Create or dry-run the schema v2 storage root"
    )
    _add_config(bootstrap)
    bootstrap.add_argument("--dry-run", action="store_true")
    bootstrap.add_argument("--adopt", action="store_true")

    storage_cmd = subparsers.add_parser("storage", help="Audit schema v2 storage")
    _add_config(storage_cmd)
    storage_cmd.add_argument("action", choices=("audit",))
    storage_cmd.add_argument("--json", action="store_true")

    import_cmd = subparsers.add_parser(
        "import", help="Plan, approve, apply, and verify whole Git repositories"
    )
    _add_config(import_cmd)
    import_sub = import_cmd.add_subparsers(dest="import_action", required=True)
    import_plan = import_sub.add_parser("plan")
    import_plan.add_argument("--source", action="append", required=True)
    import_plan.add_argument(
        "--project-state", choices=("Active", "Reference", "Completed"), default="Active"
    )
    import_plan.add_argument("--output-dir")
    import_review = import_sub.add_parser("review")
    import_review.add_argument("--plan", required=True)
    import_review.add_argument("--approve")
    import_review.add_argument("--destination")
    import_review.add_argument("--note", default="")
    import_apply = import_sub.add_parser("apply")
    import_apply.add_argument("--plan", required=True)
    import_apply.add_argument("--execute", action="store_true")
    import_verify = import_sub.add_parser("verify")
    import_verify.add_argument("--plan", required=True)

    doctor = subparsers.add_parser("doctor", help="Check environment and configuration")
    _add_config(doctor)
    doctor.add_argument("--json", action="store_true")

    validate = subparsers.add_parser("validate", help="Validate KnowledgeVault files and metadata")
    _add_config(validate)
    validate.add_argument("--json", action="store_true")

    scan_cmd = subparsers.add_parser("scan", help="Create a read-only inventory of a directory")
    _add_config(scan_cmd)
    scan_cmd.add_argument("source")
    scan_cmd.add_argument(
        "--hash-mode",
        choices=("none", "duplicates", "selected", "all"),
        help="Override configured hash mode",
    )
    scan_cmd.add_argument("--allow-system-root", action="store_true")

    plan_cmd = subparsers.add_parser("plan", help="Create a migration plan from a scan run")
    _add_config(plan_cmd)
    plan_cmd.add_argument("--run", required=True, help="Scan run ID or path inside Runtime/runs")

    report_cmd = subparsers.add_parser("report", help="Generate a consolidated run report")
    _add_config(report_cmd)
    report_cmd.add_argument("--run", required=True)

    verify_cmd = subparsers.add_parser("verify", help="Re-verify migrated destinations")
    _add_config(verify_cmd)
    verify_cmd.add_argument("--run", required=True)

    cleanup_cmd = subparsers.add_parser(
        "cleanup-plan", help="Create a manual-only source cleanup plan"
    )
    _add_config(cleanup_cmd)
    cleanup_cmd.add_argument("--run", required=True)
    cleanup_cmd.add_argument("--retention-days", type=int, default=30)

    index_cmd = subparsers.add_parser("index", help="Rebuild or verify the SQLite/FTS5 catalog")
    _add_config(index_cmd)
    index_mode = index_cmd.add_mutually_exclusive_group(required=True)
    index_mode.add_argument("--rebuild", action="store_true")
    index_mode.add_argument("--integrity", action="store_true")

    search_cmd = subparsers.add_parser("search", help="Search the SQLite FTS5 catalog")
    _add_config(search_cmd)
    search_cmd.add_argument("query")
    search_cmd.add_argument("--limit", type=int, default=20)
    search_cmd.add_argument("--json", action="store_true")

    extract_cmd = subparsers.add_parser(
        "extract", help="Extract allowed asset text into the rebuildable cache"
    )
    _add_config(extract_cmd)
    extract_cmd.add_argument("--rebuild", action="store_true", required=True)

    suggest_cmd = subparsers.add_parser(
        "suggest", help="Generate local MOC, stale, and duplicate suggestions"
    )
    _add_config(suggest_cmd)
    suggest_cmd.add_argument(
        "--kind", choices=("moc", "stale", "duplicates", "all"), default="all"
    )

    backup_cmd = subparsers.add_parser("backup", help="Manage the manual encrypted backup")
    _add_config(backup_cmd)
    backup_cmd.add_argument(
        "action", choices=("preflight", "init", "run", "check", "snapshots", "restore-drill")
    )

    restore_cmd = subparsers.add_parser("restore", help="Run a verified restore drill")
    _add_config(restore_cmd)
    restore_cmd.add_argument("action", choices=("drill",))

    profile_cmd = subparsers.add_parser(
        "windows-data", help="Create a read-only Windows profile redirection plan"
    )
    _add_config(profile_cmd)
    profile_cmd.add_argument("action", choices=("audit",))
    profile_cmd.add_argument("--home")

    codex_storage_cmd = subparsers.add_parser(
        "codex-storage",
        help="Audit Codex storage boundaries and create manual-only cleanup plans",
    )
    _add_config(codex_storage_cmd)
    codex_storage_sub = codex_storage_cmd.add_subparsers(
        dest="codex_storage_action", required=True
    )
    codex_storage_audit = codex_storage_sub.add_parser("audit")
    codex_storage_audit.add_argument("--home")
    codex_storage_audit.add_argument("--temp")
    codex_storage_audit.add_argument("--json", action="store_true")
    codex_storage_cleanup = codex_storage_sub.add_parser("cleanup-plan")
    codex_storage_cleanup.add_argument("--home")
    codex_storage_cleanup.add_argument("--temp")
    codex_storage_cleanup.add_argument("--retention-days", type=int)

    rag_cmd = subparsers.add_parser("rag", help="Build and query the local RAG sources layer")
    _add_config(rag_cmd)
    rag_sub = rag_cmd.add_subparsers(dest="rag_action", required=True)
    rag_sub.add_parser("build", help="Build/update the RAG index")
    rag_sub.add_parser("rebuild", help="Rebuild the RAG index")
    rag_sources = rag_sub.add_parser("sources", help="Return source chunks for a question")
    rag_sources.add_argument("query")
    rag_sources.add_argument("--limit", type=int)
    rag_sources.add_argument("--json", action="store_true")
    rag_search = rag_sub.add_parser("search", help="Alias for sources")
    rag_search.add_argument("query")
    rag_search.add_argument("--limit", type=int)
    rag_search.add_argument("--json", action="store_true")

    ask_cmd = subparsers.add_parser("ask", help="Answer from RAG sources, optionally through Ollama")
    _add_config(ask_cmd)
    ask_cmd.add_argument("question")
    ask_cmd.add_argument("--sources-only", action="store_true")
    ask_cmd.add_argument("--json", action="store_true")
    ask_cmd.add_argument("--limit", type=int)

    wiki_cmd = subparsers.add_parser("wiki", help="Create and review wiki drafts")
    _add_config(wiki_cmd)
    wiki_sub = wiki_cmd.add_subparsers(dest="wiki_action", required=True)
    wiki_sub.add_parser("suggest-links")
    wiki_concept = wiki_sub.add_parser("draft-concept")
    wiki_concept.add_argument("concept")
    wiki_summary = wiki_sub.add_parser("summarize")
    wiki_summary.add_argument("path")
    wiki_moc = wiki_sub.add_parser("draft-moc")
    wiki_moc.add_argument("topic")
    wiki_approve = wiki_sub.add_parser("approve")
    wiki_approve.add_argument("--draft", required=True)
    wiki_approve.add_argument("--target", required=True)
    wiki_apply = wiki_sub.add_parser("apply")
    wiki_apply.add_argument("--draft", required=True)
    wiki_apply.add_argument("--execute", action="store_true")

    graph_cmd = subparsers.add_parser("graph", help="Build and export the KnowledgeVault graph")
    _add_config(graph_cmd)
    graph_sub = graph_cmd.add_subparsers(dest="graph_action", required=True)
    graph_sub.add_parser("build")
    graph_neighbors_cmd = graph_sub.add_parser("neighbors")
    graph_neighbors_cmd.add_argument("query")
    graph_export = graph_sub.add_parser("export")
    graph_export.add_argument("--format", choices=("json", "mermaid", "graphml"), required=True)
    graph_sub.add_parser("stats")

    route = subparsers.add_parser("route", help="Create an immutable routing plan from Staging/Inbox")
    _add_config(route)

    review = subparsers.add_parser("review", help="Inspect or approve a route")
    _add_config(review)
    review.add_argument("--plan", required=True)
    review.add_argument("--approve", metavar="ROUTE_ID")
    review.add_argument("--destination", help="Relative destination inside KnowledgeVault root")
    review.add_argument("--note", default="", help="Reviewer note for migration plans")

    apply_cmd = subparsers.add_parser("apply", help="Dry-run or execute approved routes")
    _add_config(apply_cmd)
    apply_cmd.add_argument("--plan", required=True)
    apply_cmd.add_argument("--execute", action="store_true")
    return parser


def _print_routes(routes) -> None:
    if not routes:
        print("Inbox або план порожній.")
        return
    for route in routes:
        print(f"[{route.status.upper():8}] {route.confidence:.2f} {Path(route.source).name} -> {route.destination}")
        print(f"           id={route.route_id} | {route.reason}")
        if route.result:
            print(f"           result={route.result}")


def _run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config_path = discover_config_path(
            getattr(args, "config", None), getattr(args, "root", None)
        )
        config = load_config(config_path, getattr(args, "root", None))
    except Exception as exc:
        print(f"[FAIL] configuration: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.command == "init":
        result = initialize(
            config,
            dry_run=args.dry_run,
            force_template_update=args.force_template_update,
        )
        for item in result.created:
            print(f"[{'WOULD CREATE' if args.dry_run else 'CREATED'}] {item}")
        for item in result.updated:
            print(f"[{'WOULD UPDATE' if args.dry_run else 'UPDATED'}] {item}")
        for item in result.skipped:
            print(f"[SKIPPED] {item}")
        return 0

    if args.command == "bootstrap":
        try:
            result = bootstrap_storage(
                config, dry_run=args.dry_run, adopt=args.adopt
            )
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            print(f"[FAIL] bootstrap: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.command == "storage":
        result = audit_storage(config)
        payload = asdict(result)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(
                f"[{'PASS' if result.marker_valid and not result.errors else 'FAIL'}] "
                f"marker={result.marker_valid} missing={len(result.missing_directories)} "
                f"reparse={len(result.reparse_points)} root_git={result.unexpected_root_git}"
            )
        return 1 if result.errors or result.missing_directories or result.unexpected_root_git else 0

    if args.command == "import":
        try:
            if args.import_action == "plan":
                plan, records = create_repository_plan(
                    config,
                    args.source,
                    project_state=args.project_state,
                    output_dir=args.output_dir,
                )
                print(f"[PASS] Repository plan: {plan}")
                print(
                    f"       repositories={len(records)} "
                    f"blocked={sum(item.review_status == 'blocked' for item in records)}"
                )
                return 0
            if args.import_action == "review":
                if args.destination and not args.approve:
                    raise ValueError("--destination requires --approve")
                if args.approve:
                    selected = approve_repository(
                        args.plan,
                        args.approve,
                        config,
                        destination=args.destination,
                        note=args.note,
                    )
                    print(f"[PASS] Approved {selected.repository_id} -> {selected.destination}")
                for item in effective_repository_plan(args.plan):
                    print(f"[{item.review_status.upper():8}] {item.source} -> {item.destination}")
                return 0
            if args.import_action == "apply":
                if not args.execute:
                    for item in effective_repository_plan(args.plan):
                        print(f"[{item.review_status.upper():8}] {item.source} -> {item.destination}")
                    print("Dry-run: no repository was copied. Add --execute after review.")
                    return 0
                events = apply_repository_plan(args.plan, config)
                print(json.dumps(events, ensure_ascii=False, indent=2))
                return 1 if any(str(item.get("result", "")).startswith("error:") for item in events) else 0
            results = verify_repository_plan(args.plan)
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 1 if any(not item.get("verified") for item in results) else 0
        except Exception as exc:
            print(f"[FAIL] import: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.command == "doctor":
        checks = run_doctor(config)
        if args.json:
            print(json.dumps(checks_as_dict(checks), ensure_ascii=False, indent=2))
        else:
            for check in checks:
                print(f"[{check.level:4}] {check.name}: {check.message}")
        return 1 if has_failures(checks) else 0

    if args.command == "validate":
        findings = validate_vault(config)
        if args.json:
            print(json.dumps(findings_as_dict(findings), ensure_ascii=False, indent=2))
        elif not findings:
            print("[PASS] Помилок і попереджень не знайдено.")
        else:
            for finding in findings:
                print(f"[{finding.level:5}] {finding.code}: {finding.path}: {finding.message}")
        return 1 if has_errors(findings) else 0

    if args.command == "scan":
        try:
            result = scan(
                args.source,
                config,
                hash_mode=args.hash_mode,
                allow_system_root=args.allow_system_root,
            )
        except Exception as exc:
            print(f"[FAIL] scan: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(f"[PASS] Read-only scan completed: {result.run_id}")
        print(f"       files={len(result.items)} errors={len(result.errors)}")
        print(f"       report={result.run_dir / 'report.md'}")
        return 1 if result.errors else 0

    if args.command == "plan":
        try:
            plan_path, rows = create_plan(args.run, config)
        except Exception as exc:
            print(f"[FAIL] plan: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(f"[PASS] Migration plan created: {plan_path}")
        print(
            "       "
            f"rows={len(rows)} "
            f"manual={sum(row.review_status == 'manual' for row in rows)} "
            f"duplicates={sum(row.exact_duplicate for row in rows)} "
            f"collisions={sum(row.name_collision for row in rows)}"
        )
        return 0

    if args.command == "report":
        try:
            print(f"[PASS] Report: {generate_report(args.run, config)}")
        except Exception as exc:
            print(f"[FAIL] report: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "verify":
        try:
            output, rows = verify_run(args.run, config)
            print(f"[PASS] Verified {len(rows)} migrated files: {output}")
        except Exception as exc:
            print(f"[FAIL] verify: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "cleanup-plan":
        if args.retention_days < 1:
            print("--retention-days must be positive", file=sys.stderr)
            return 2
        try:
            output = create_cleanup_plan(args.run, config, args.retention_days)
            print(f"[PASS] Manual-only cleanup plan: {output}")
        except Exception as exc:
            print(f"[FAIL] cleanup-plan: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "index":
        try:
            if args.rebuild:
                summary = rebuild_index(config)
                print(f"[PASS] Catalog rebuilt: {summary.database}")
                print(
                    f"       objects={summary.objects} files={summary.files} "
                    f"assets={summary.assets} relations={summary.relations} "
                    f"scan_runs={summary.scan_runs} errors={summary.errors}"
                )
            else:
                print(f"[PASS] Catalog integrity: {integrity_check(config)}")
        except Exception as exc:
            print(f"[FAIL] index: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "search":
        if args.limit < 1 or args.limit > 100:
            print("--limit must be between 1 and 100", file=sys.stderr)
            return 2
        try:
            results = search_index(config, args.query, args.limit)
        except Exception as exc:
            print(f"[FAIL] search: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        elif not results:
            print("Нічого не знайдено.")
        else:
            for item in results:
                print(f"- {item['title']} ({item['uid']})")
                print(f"  {item['snippet']}")
        return 0

    if args.command == "extract":
        try:
            manifest, results = rebuild_extractions(config)
            print(
                f"[PASS] Extraction cache rebuilt: {manifest}\n"
                f"       extracted={sum(item.status == 'extracted' for item in results)} "
                f"skipped={sum(item.status == 'skipped' for item in results)} "
                f"errors={sum(item.status == 'error' for item in results)}"
            )
        except Exception as exc:
            print(f"[FAIL] extract: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "suggest":
        try:
            print(f"[PASS] Suggestions: {generate_suggestions(config, args.kind)}")
        except Exception as exc:
            print(f"[FAIL] suggest: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "backup":
        try:
            if args.action == "preflight":
                checks = backup_preflight(config)
                print(
                    json.dumps(
                        [asdict(item) for item in checks], ensure_ascii=False, indent=2
                    )
                )
                return 1 if any(item.level == "FAIL" for item in checks) else 0
            if args.action == "init":
                result = backup_init(config)
                print(f"[PASS] {result.output}")
            elif args.action == "run":
                for result in backup_run(config):
                    print(f"[PASS] {result.output}")
            elif args.action == "check":
                print(f"[PASS] {backup_check(config).output}")
            elif args.action == "snapshots":
                print(json.dumps(backup_snapshots(config), ensure_ascii=False, indent=2))
            else:
                print(
                    "[PASS] "
                    + json.dumps(
                        backup_restore_drill(config), ensure_ascii=False, indent=2
                    )
                )
        except Exception as exc:
            print(f"[FAIL] backup: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "restore":
        try:
            print(
                "[PASS] "
                + json.dumps(
                    backup_restore_drill(config), ensure_ascii=False, indent=2
                )
            )
            return 0
        except Exception as exc:
            print(f"[FAIL] restore: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.command == "windows-data":
        try:
            output, items = audit_windows_profile(config, home=args.home)
            print(f"[PASS] Windows profile audit: {output}")
            print(json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            print(f"[FAIL] windows-data: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.command == "codex-storage":
        try:
            if args.codex_storage_action == "audit":
                output, payload = audit_codex_storage(
                    config, home=args.home, temp=args.temp
                )
                if args.json:
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    status = "PASS" if payload["codex_home_matches"] else "FAIL"
                    print(f"[{status}] Codex storage audit: {output}")
                    print(
                        "       "
                        f"CODEX_HOME={payload['effective_codex_home']} "
                        f"expected={payload['expected_codex_home']} "
                        f"cleanup_candidates={payload['cleanup_candidate_count']}"
                    )
                return 0 if payload["codex_home_matches"] else 1
            output, payload = create_codex_cleanup_plan(
                config,
                home=args.home,
                temp=args.temp,
                retention_days=args.retention_days,
            )
            print(f"[PASS] Manual-only Codex cleanup plan: {output}")
            print(
                "       "
                f"rows={len(payload['rows'])} "
                f"eligible={sum(bool(row['eligible']) for row in payload['rows'])} "
                "execute_supported=false"
            )
            return 0
        except Exception as exc:
            print(f"[FAIL] codex-storage: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.command == "rag":
        try:
            if args.rag_action in {"build", "rebuild"}:
                summary = rebuild_rag(config, incremental=args.rag_action == "build")
                print(
                    f"[PASS] RAG {summary.mode}: {summary.database}\n"
                    f"       run={summary.run_id} sources={summary.sources} "
                    f"chunks={summary.chunks} embeddings={summary.embeddings} "
                    f"changed={summary.changed_sources} reused={summary.reused_sources} "
                    f"removed={summary.removed_sources} seconds={summary.duration_seconds:.2f}"
                )
                return 0
            rows = query_sources(config, args.query, args.limit)
            write_sources_report(config, args.query, rows)
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            elif not rows:
                print("Недостатньо джерел.")
            else:
                for index, row in enumerate(rows, 1):
                    print(f"{index}. {row['title']} — {row['source_path']}")
                    print(f"   heading={row.get('heading_path') or ''}")
                    print(f"   chunk={row['chunk_id']}")
                    print(f"   {str(row.get('snippet', '')).replace(chr(10), ' ')}")
            return 0
        except Exception as exc:
            print(f"[FAIL] rag: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.command == "ask":
        try:
            result = ask(config, args.question, sources_only=args.sources_only, limit=args.limit)
            if args.json:
                print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
            else:
                print(ask_as_markdown(result))
            return 0
        except Exception as exc:
            print(f"[FAIL] ask: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.command == "wiki":
        try:
            if args.wiki_action == "suggest-links":
                draft = suggest_links(config)
                print(f"[PASS] Wiki draft: {draft.path}")
            elif args.wiki_action == "draft-concept":
                draft = draft_concept(config, args.concept)
                print(f"[PASS] Wiki draft: {draft.path}")
            elif args.wiki_action == "summarize":
                draft = summarize_path(config, args.path)
                print(f"[PASS] Wiki draft: {draft.path}")
            elif args.wiki_action == "draft-moc":
                draft = draft_moc(config, args.topic)
                print(f"[PASS] Wiki draft: {draft.path}")
            elif args.wiki_action == "approve":
                print(f"[PASS] Approval: {approve_draft(config, args.draft, args.target)}")
            elif args.wiki_action == "apply":
                print(f"[PASS] Wiki apply artifact: {apply_draft(config, args.draft, execute=args.execute)}")
            return 0
        except Exception as exc:
            print(f"[FAIL] wiki: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.command == "graph":
        try:
            if args.graph_action == "build":
                summary = build_graph(config)
                print(
                    f"[PASS] Graph built: {summary.output}\n"
                    f"       nodes={summary.nodes} edges={summary.edges} orphans={summary.orphans}"
                )
            elif args.graph_action == "neighbors":
                print(json.dumps(graph_neighbors(config, args.query), ensure_ascii=False, indent=2))
            elif args.graph_action == "export":
                print(f"[PASS] Graph export: {export_graph(config, args.format)}")
            elif args.graph_action == "stats":
                print(json.dumps(graph_stats(config), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            print(f"[FAIL] graph: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.command == "route":
        routes = inventory(config)
        run_dir = create_run(config, routes)
        _print_routes(routes)
        print(f"\nПлан: {run_dir / 'route_plan.jsonl'}")
        print("Dry-run: файли не копіювалися.")
        return 0

    if args.command == "review":
        if args.destination and not args.approve:
            print("--destination requires --approve", file=sys.stderr)
            return 2
        if is_migration_plan(args.plan):
            if args.approve:
                selected = approve_migration_row(
                    args.plan, args.approve, config, args.destination, args.note
                )
                print(
                    f"Затверджено: {selected.row_id} -> {selected.destination_path}"
                )
            rows = effective_migration_plan(args.plan)
            for row in rows:
                print(
                    f"[{row.review_status.upper():8}] {row.operation:13} "
                    f"{Path(row.source_path).name} -> {row.destination_path}"
                )
                print(f"           id={row.row_id} | {row.reason}")
        else:
            if args.approve:
                selected = approve_route(args.plan, args.approve, config, args.destination)
                print(f"Затверджено: {selected.route_id} -> {selected.destination}")
            _print_routes(effective_plan(args.plan))
        return 0

    if args.command == "apply":
        if is_migration_plan(args.plan):
            rows = effective_migration_plan(args.plan)
            approved = [row for row in rows if row.review_status == "approved"]
            if not args.execute:
                for row in rows:
                    print(
                        f"[{row.review_status.upper():8}] {row.operation:13} "
                        f"{Path(row.source_path).name} -> {row.destination_path}"
                    )
                print(
                    f"Dry-run: approved={len(approved)}; копіювання не виконувалося."
                )
                return 0
            events = execute_migration_plan(args.plan, config)
            for event in events:
                print(
                    f"[{event['result']}] {event['source_path']} -> "
                    f"{event['destination_path']}"
                )
            return 1 if any(
                str(event["result"]).startswith("error:") for event in events
            ) else 0
        if not args.execute:
            _print_routes(effective_plan(args.plan))
            print("Dry-run: копіювання не виконувалося. Додайте --execute після перевірки.")
            return 0
        routes = execute_plan(args.plan, config)
        _print_routes(routes)
        return 1 if any(route.result and route.result.startswith("error:") for route in routes) else 0
    return 2


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    started = time.perf_counter()
    command = effective_argv[0] if effective_argv else "unknown"
    try:
        parsed = _parser().parse_args(effective_argv)
    except SystemExit:
        raise
    try:
        config_path = discover_config_path(
            getattr(parsed, "config", None), getattr(parsed, "root", None)
        )
        config = load_config(config_path, getattr(parsed, "root", None))
    except Exception:
        return _run(effective_argv)
    exit_code = _run(effective_argv)
    dry_run = bool(getattr(parsed, "dry_run", False))
    no_write_dry_run = (command == "bootstrap" and dry_run) or (
        command == "init" and dry_run and config.schema_version == 2
    )
    read_only_preflight = command == "storage" or (
        command == "backup" and getattr(parsed, "action", None) == "preflight"
    )
    uninitialized_v2 = config.schema_version == 2 and not marker_path(config).is_file()
    if not (no_write_dry_run or read_only_preflight or uninitialized_v2):
        record_command(
            config,
            command,
            exit_code,
            int((time.perf_counter() - started) * 1000),
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
