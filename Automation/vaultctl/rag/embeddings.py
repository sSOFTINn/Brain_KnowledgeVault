from __future__ import annotations

from hashlib import sha256
import json
import math
import struct
import urllib.request

from vaultctl.config import Config
from vaultctl.local_http import open_local_request, validate_local_base_url


def vector_to_blob(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def blob_to_vector(blob: bytes) -> list[float]:
    if not blob:
        return []
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def test_embedding(text: str, dimension: int = 64) -> list[float]:
    digest = sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < dimension:
        for byte in digest:
            values.append((byte / 127.5) - 1.0)
            if len(values) == dimension:
                break
        digest = sha256(digest).digest()
    return values


def embed_text(config: Config, text: str) -> list[float] | None:
    embeddings = config.rag.embeddings
    if not embeddings.enabled or embeddings.provider == "none":
        return None
    if embeddings.provider == "test":
        return test_embedding(text, embeddings.dimension or 64)
    if embeddings.provider == "ollama":
        payload = json.dumps({"model": embeddings.model, "prompt": text}).encode("utf-8")
        request = urllib.request.Request(
            validate_local_base_url(config.llm.base_url) + "/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with open_local_request(request, expected_path="/api/embeddings", timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        vector = data.get("embedding")
        if not isinstance(vector, list):
            raise RuntimeError("Ollama embeddings response has no embedding")
        return [float(item) for item in vector]
    raise ValueError(f"Unsupported embeddings provider: {embeddings.provider}")
