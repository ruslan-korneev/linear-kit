"""Thin GraphQL client for the Linear API."""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

ENDPOINT = "https://api.linear.app/graphql"


class LinearError(RuntimeError):
    """A GraphQL-level or transport-level failure."""


class RateLimited(LinearError):
    """Linear reports rate limiting as HTTP 400 + code RATELIMITED, not 429."""

    def __init__(self, message: str, reset_at: float | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


def new_id() -> str:
    """Client-supplied UUID v4. Every Linear create input accepts `id`, which
    makes a retried mutation idempotent instead of creating a duplicate."""
    return str(uuid.uuid4())


class LinearClient:
    def __init__(self, api_key: str, *, timeout: float = 30.0, max_retries: int = 3) -> None:
        # Personal API keys go in Authorization raw — no Bearer prefix.
        self._http = httpx.Client(
            base_url=ENDPOINT,
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._max_retries = max_retries

    def __enter__(self) -> "LinearClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"query": query, "variables": variables or {}}
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                response = self._http.post("", json=payload)
            except httpx.RequestError as exc:
                last_error = LinearError(f"Request to Linear failed: {exc}")
                time.sleep(2**attempt)
                continue

            try:
                body = response.json()
            except ValueError:
                raise LinearError(
                    f"Linear returned HTTP {response.status_code} with a non-JSON body: "
                    f"{response.text[:400]}"
                ) from None

            errors = body.get("errors")
            if errors:
                if _is_rate_limited(errors):
                    reset_at = _reset_at(response)
                    if attempt == self._max_retries - 1:
                        raise RateLimited(_format_errors(errors), reset_at)
                    time.sleep(_backoff_seconds(reset_at, attempt))
                    continue
                raise LinearError(_format_errors(errors))

            if response.status_code >= 400:
                raise LinearError(f"HTTP {response.status_code}: {response.text[:400]}")

            return body.get("data") or {}

        raise last_error or LinearError("Exhausted retries against the Linear API.")

    def mutate(self, query: str, variables: dict[str, Any], root: str) -> dict[str, Any]:
        """Run a mutation and unwrap its payload, asserting `success`.

        Linear payloads return {success, lastSyncId, <entity>}; a falsy `success`
        with no `errors` block is possible, so checking it is not redundant.
        """
        data = self.execute(query, variables)
        payload = data.get(root)
        if payload is None:
            raise LinearError(f"Mutation {root} returned no payload.")
        if not payload.get("success", False):
            raise LinearError(f"Mutation {root} reported success=false: {payload}")
        return payload


def _is_rate_limited(errors: list[dict[str, Any]]) -> bool:
    return any(e.get("extensions", {}).get("code") == "RATELIMITED" for e in errors)


def _format_errors(errors: list[dict[str, Any]]) -> str:
    """Prefer Linear's userPresentableMessage over `message`.

    `message` is often a bare "Access denied" while userPresentableMessage
    carries the actual cause, e.g. hitting the plan's team limit.
    """
    parts: list[str] = []
    for error in errors:
        extensions = error.get("extensions", {})
        detail = extensions.get("userPresentableMessage") or error.get("message") or str(error)
        code = extensions.get("code")
        parts.append(f"{detail} [{code}]" if code and code not in detail else detail)
    return "; ".join(parts)


def _reset_at(response: httpx.Response) -> float | None:
    raw = response.headers.get("X-RateLimit-Requests-Reset")
    if not raw:
        return None
    try:
        return float(raw) / 1000.0  # header is epoch milliseconds
    except ValueError:
        return None


def _backoff_seconds(reset_at: float | None, attempt: int) -> float:
    if reset_at:
        wait = reset_at - time.time()
        if 0 < wait <= 60:
            return wait + 1
    return min(2**attempt, 30)
