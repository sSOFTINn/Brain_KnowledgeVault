from __future__ import annotations

from urllib.error import HTTPError
from urllib.parse import SplitResult, urlsplit
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _validate_url(value: str, *, origin_only: bool) -> SplitResult:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("local service URL is invalid") from exc
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("local service URL must use http or https")
    if (parsed.hostname or "").casefold() not in LOOPBACK_HOSTS:
        raise ValueError("local service URL must use localhost, 127.0.0.1, or ::1")
    if parsed.username or parsed.password:
        raise ValueError("local service URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("local service URL must not contain query or fragment")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("local service URL port is invalid")
    if origin_only and parsed.path not in {"", "/"}:
        raise ValueError("local service base URL must not contain a path")
    return parsed


def validate_local_base_url(value: str) -> str:
    _validate_url(value, origin_only=True)
    return value.rstrip("/")


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "redirects are disabled", headers, fp)


def _opener() -> OpenerDirector:
    return build_opener(_NoRedirectHandler())


def open_local_request(request: Request, *, expected_path: str, timeout: int):
    requested = _validate_url(request.full_url, origin_only=False)
    if requested.path != expected_path:
        raise ValueError(f"unexpected local service path: {requested.path}")
    response = _opener().open(request, timeout=timeout)
    final = _validate_url(response.geturl(), origin_only=False)
    if (
        final.scheme != requested.scheme
        or final.hostname != requested.hostname
        or final.port != requested.port
        or final.path != expected_path
    ):
        response.close()
        raise RuntimeError("local service response changed origin or path")
    return response
