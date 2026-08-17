from __future__ import annotations

from dataclasses import dataclass, field
import json
import urllib.error
import urllib.request

from .config import Config
from .local_http import open_local_request, validate_local_base_url
from .rag.store import query_sources


@dataclass(frozen=True)
class AskResult:
    question: str
    answer: str
    sources: list[dict]
    mode: str
    sufficient_sources: bool
    citations: list[str] = field(default_factory=list)
    citation_status: str = "not-applicable"


def _format_sources(rows: list[dict]) -> str:
    lines: list[str] = []
    for index, row in enumerate(rows, 1):
        heading = row.get("heading_path") or ""
        lines.append(
            f"[{index}] {row['title']} | {row['source_path']} | {heading} | chunk={row['chunk_id']}"
        )
        lines.append(str(row.get("snippet", "")).replace("\n", " "))
    return "\n".join(lines)


def _bounded_sources(config: Config, question: str, sources: list[dict]) -> list[dict]:
    fixed = (
        "Answer only from the provided KnowledgeVault sources. Return structured JSON.\n"
        f"Question:\n{question}\nSources:\n"
    )
    budget = config.llm.context_limit_tokens
    selected: list[dict] = []
    for source in sources:
        candidate = [*selected, source]
        estimated_tokens = (len(fixed) + len(_format_sources(candidate)) + 3) // 4
        if estimated_tokens > budget:
            break
        selected.append(source)
    return selected


def _ollama_answer(config: Config, question: str, sources: list[dict]) -> tuple[str, list[str]]:
    prompt = f"""Answer only from the provided KnowledgeVault sources.
Return one JSON object with exactly these fields:
- "answer": a non-empty string grounded in the sources;
- "citations": a non-empty array containing only exact chunk_id values from Sources.
Do not invent chunk IDs and do not include Markdown fences.

Question:
{question}

Sources:
{_format_sources(sources)}
"""
    payload = json.dumps(
        {
            "model": config.llm.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": config.llm.temperature,
                "num_ctx": config.llm.context_limit_tokens,
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        validate_local_base_url(config.llm.base_url) + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with open_local_request(request, expected_path="/api/generate", timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Ollama is unavailable: {exc}") from exc
    raw_response = data.get("response", "")
    try:
        structured = json.loads(raw_response) if isinstance(raw_response, str) else raw_response
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama returned malformed structured JSON") from exc
    if not isinstance(structured, dict):
        raise RuntimeError("Ollama structured response must be a JSON object")
    answer = str(structured.get("answer", "")).strip()
    if not answer:
        raise RuntimeError("Ollama returned an empty response")
    citations = structured.get("citations")
    if not isinstance(citations, list) or not citations:
        raise RuntimeError("Ollama response has no citations")
    allowed = {str(row["chunk_id"]) for row in sources}
    normalized: list[str] = []
    for citation in citations:
        chunk_id = str(citation)
        if chunk_id not in allowed:
            raise RuntimeError(f"Ollama returned an unknown citation: {chunk_id}")
        if chunk_id not in normalized:
            normalized.append(chunk_id)
    return answer, normalized


def ask(config: Config, question: str, *, sources_only: bool = False, limit: int | None = None) -> AskResult:
    sources = query_sources(config, question, limit)
    sufficient = bool(sources)
    if sources_only:
        answer = (
            "Знайдені джерела наведені нижче. LLM не викликався."
            if sufficient
            else "Недостатньо джерел для відповіді."
        )
        return AskResult(question, answer, sources, "sources-only", sufficient, [], "not-applicable")
    if not sufficient:
        return AskResult(question, "Недостатньо джерел для відповіді.", [], "llm", False, [], "insufficient-sources")
    if not config.llm.enabled:
        raise RuntimeError("LLM disabled. Use `ask --sources-only` or enable [llm] in vault.toml.")
    if config.llm.provider != "ollama":
        raise RuntimeError("Only Ollama LLM provider is supported")
    bounded = _bounded_sources(config, question, sources)
    if not bounded:
        return AskResult(
            question,
            "Недостатньо контекстного бюджету для відповіді.",
            [],
            "llm",
            False,
            [],
            "context-limit",
        )
    answer, citations = _ollama_answer(config, question, bounded)
    return AskResult(question, answer, bounded, "ollama", True, citations, "validated")


def ask_as_markdown(result: AskResult) -> str:
    lines = [f"# Відповідь", "", f"**Питання:** {result.question}", "", result.answer, ""]
    if result.citations:
        source_numbers = {
            str(row["chunk_id"]): index for index, row in enumerate(result.sources, 1)
        }
        markers = [f"[{source_numbers[item]}]" for item in result.citations]
        lines.extend([f"**Citations:** {', '.join(markers)}", ""])
    lines.append("## Sources")
    lines.append("")
    if not result.sources:
        lines.append("Немає достатніх джерел.")
    for index, row in enumerate(result.sources, 1):
        lines.append(f"{index}. `{row['source_path']}` — {row['title']}")
        if row.get("heading_path"):
            lines.append(f"   - Heading: {row['heading_path']}")
        lines.append(f"   - Chunk: `{row['chunk_id']}`")
        lines.append(f"   - Snippet: {str(row.get('snippet', '')).replace(chr(10), ' ')}")
    return "\n".join(lines).rstrip() + "\n"
