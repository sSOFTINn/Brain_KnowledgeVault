from __future__ import annotations

from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
import sqlite3

from .config import Config
from .dashboard import write_dashboard
from .indexer import rebuild_index
from .locks import vault_lock


@dataclass(frozen=True)
class GraphSummary:
    nodes: int
    edges: int
    orphans: int
    output: Path


def _catalog(config: Config) -> Path:
    database = config.runtime / (
        "Catalog/catalog.sqlite3" if config.schema_version == 2 else "db/catalog.sqlite3"
    )
    if not database.is_file():
        rebuild_index(config)
    return database


def build_graph(config: Config) -> GraphSummary:
    database = _catalog(config)
    graph_dir = config.runtime / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    with vault_lock(config, "graph-build"):
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            objects = [dict(row) for row in connection.execute(
                "SELECT uid,type,title,status,path,visibility,updated FROM objects WHERE visibility IN ('public','internal')"
            )]
            nodes_by_uid = {row["uid"]: row for row in objects}
            edges: list[dict] = []
            for row in connection.execute("SELECT source_uid,target,relation_type FROM relations"):
                source = row["source_uid"]
                target = row["target"]
                if source in nodes_by_uid and (target in nodes_by_uid or not re.match(r"^[0-9a-f-]{32,}$", target)):
                    edges.append({"source": source, "target": target, "type": row["relation_type"], "source_kind": "automatic"})
            for row in connection.execute("SELECT uid, code FROM projects WHERE code IS NOT NULL AND code != ''"):
                if row["uid"] in nodes_by_uid:
                    edges.append({"source": row["uid"], "target": row["code"], "type": "belongs_to_project", "source_kind": "automatic"})
            titles = {row["uid"]: str(row["title"]).casefold() for row in objects}
            note_bodies = connection.execute("SELECT uid, body FROM notes").fetchall()
            for note in note_bodies:
                source = note["uid"]
                if source not in nodes_by_uid:
                    continue
                body = str(note["body"]).casefold()
                for target_uid, title in titles.items():
                    if target_uid != source and title and title in body:
                        edges.append({"source": source, "target": target_uid, "type": "mentions", "source_kind": "deterministic"})
        finally:
            connection.close()
        node_ids = {node["uid"] for node in objects}
        connected = {edge["source"] for edge in edges if edge["source"] in node_ids} | {edge["target"] for edge in edges if edge["target"] in node_ids}
        graph = {"nodes": objects, "edges": edges}
        output = graph_dir / "graph.json"
        output.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_mermaid(graph_dir / "graph.mmd", objects, edges)
        _write_graphml(graph_dir / "graph.graphml", objects, edges)
    write_dashboard(config)
    return GraphSummary(len(objects), len(edges), len(node_ids - connected), output)


def _safe_id(value: str) -> str:
    return "n" + re.sub(r"[^A-Za-z0-9_]", "_", value)


def _write_mermaid(path: Path, nodes: list[dict], edges: list[dict]) -> None:
    labels = {node["uid"]: str(node["title"]).replace('"', "'") for node in nodes}
    lines = ["graph TD"]
    for uid, label in labels.items():
        lines.append(f'  {_safe_id(uid)}["{label}"]')
    for edge in edges:
        source = _safe_id(edge["source"])
        target = _safe_id(edge["target"])
        label = str(edge["type"]).replace('"', "'")
        if edge["target"] not in labels:
            lines.append(f'  {target}["{edge["target"]}"]')
        lines.append(f'  {source} -->|"{label}"| {target}')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_graphml(path: Path, nodes: list[dict], edges: list[dict]) -> None:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">', '<graph edgedefault="directed">']
    for node in nodes:
        lines.append(f'<node id="{html.escape(node["uid"])}"><data key="title">{html.escape(str(node["title"]))}</data></node>')
    for index, edge in enumerate(edges):
        lines.append(f'<edge id="e{index}" source="{html.escape(edge["source"])}" target="{html.escape(edge["target"])}"><data key="type">{html.escape(edge["type"])}</data></edge>')
    lines.extend(["</graph>", "</graphml>"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_graph(config: Config) -> dict:
    path = config.runtime / "graph" / "graph.json"
    if not path.is_file():
        build_graph(config)
    return json.loads(path.read_text(encoding="utf-8"))


def graph_stats(config: Config) -> dict:
    graph = load_graph(config)
    node_ids = {node["uid"] for node in graph["nodes"]}
    connected = {edge["source"] for edge in graph["edges"] if edge["source"] in node_ids} | {edge["target"] for edge in graph["edges"] if edge["target"] in node_ids}
    return {"nodes": len(node_ids), "edges": len(graph["edges"]), "orphans": len(node_ids - connected)}


def graph_neighbors(config: Config, query: str) -> list[dict]:
    graph = load_graph(config)
    matching = {
        node["uid"]
        for node in graph["nodes"]
        if query.casefold() in node["uid"].casefold() or query.casefold() in str(node["title"]).casefold()
    }
    results: list[dict] = []
    for edge in graph["edges"]:
        if edge["source"] in matching or edge["target"] in matching:
            results.append(edge)
    return results


def export_graph(config: Config, fmt: str) -> Path:
    build_graph(config)
    mapping = {"json": "graph.json", "mermaid": "graph.mmd", "graphml": "graph.graphml"}
    if fmt not in mapping:
        raise ValueError("format must be json, mermaid, or graphml")
    return config.runtime / "graph" / mapping[fmt]
