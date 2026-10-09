"""Shared HTTP plumbing for the third-party providers."""

from __future__ import annotations

import logging
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_local = threading.local()


class UpstreamError(Exception):
    """A third-party API failed or returned something unusable."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def session() -> requests.Session:
    """One pooled session per thread (requests.Session is not thread-safe)."""
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = settings.HTTP_USER_AGENT
        _local.session = s
    return s


def get_json(
    url: str,
    params: dict | None = None,
    *,
    provider: str,
    retries: int = 3,
    json_client_errors: bool = False,
    timeout: float | None = None,
) -> object:
    """GET a JSON document, retrying on rate limits and transient server errors.

    With ``json_client_errors`` a 4xx (other than 429) body is returned instead of
    raising, for APIs such as OSRM that report "no route" as HTTP 400 + JSON.
    """
    delay = 1.5
    for attempt in range(retries + 1):
        try:
            resp = session().get(url, params=params, timeout=timeout or settings.HTTP_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            if attempt == retries:
                raise UpstreamError(f"{provider} is unreachable: {exc}") from exc
            logger.warning("%s request failed (%s), retrying", provider, exc)
        else:
            if resp.status_code in RETRYABLE_STATUS and attempt < retries:
                logger.warning("%s returned %s, retrying in %.1fs", provider, resp.status_code, delay)
            elif resp.status_code >= 400 and not (
                json_client_errors and resp.status_code < 500 and resp.status_code != 429
            ):
                raise UpstreamError(_error_message(provider, resp))
            else:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise UpstreamError(f"{provider} returned invalid JSON") from exc
        time.sleep(delay)
        delay *= 2
    raise UpstreamError(f"{provider} request failed")  # pragma: no cover - loop always returns/raises


def _error_message(provider: str, resp: requests.Response) -> str:
    detail = ""
    try:
        body = resp.json()
        detail = body.get("reason") or body.get("message") or ""
    except (ValueError, AttributeError):
        pass
    if resp.status_code == 429:
        return f"{provider} rate limit reached — please wait a minute and try again."
    return f"{provider} error {resp.status_code}{': ' + detail if detail else ''}"
