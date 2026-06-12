"""
Webhook delivery handler.

Delivers an HTTP POST request to the URL specified in the job payload.
This is real network I/O — not a stub. The handler:

  1. Validates the payload has a url field
  2. Opens an httpx AsyncClient with a configurable timeout
  3. POSTs the webhook body to the target URL
  4. Inspects the HTTP response:
       - 2xx → success
       - 4xx → terminal failure (do NOT retry — client error)
       - 5xx → transient failure (retry eligible)
       - Network error / timeout → retry eligible
  5. Returns a result dict on success, raises an exception on failure

The retry vs no-retry distinction maps exactly to the priority rule
discussed earlier:
  - payment_confirmed getting a 404 means the endpoint doesn't exist
    → retrying won't help → don't waste queue slots
  - payment_confirmed getting a 503 means the endpoint is temporarily down
    → retry with backoff → it might recover

Payload structure:
{
  "url": "https://example.com/webhook",
  "event": "payment_confirmed",
  "data": { ... }
}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.logger import get_logger

log = get_logger(__name__)


class WebhookTerminalError(Exception):
    """
    4xx error — retrying will not help.
    The worker moves this job directly to failed without incrementing retry_count.
    """
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Terminal HTTP {status_code}: {body[:200]}")


class WebhookTransientError(Exception):
    """
    5xx, timeout, or network error — eligible for retry.
    The worker increments retry_count and re-queues with backoff.
    """
    def __init__(self, reason: str) -> None:
        super().__init__(reason)


async def handle(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the webhook delivery.

    Returns a result dict on success:
    {
      "status_code": 200,
      "response_body": "...",
      "delivered_at": "2026-06-01T10:00:00Z",
      "duration_ms": 234
    }

    Raises WebhookTerminalError for 4xx.
    Raises WebhookTransientError for 5xx / timeout / network error.
    """
    url: str | None = payload.get("url")
    if not url:
        raise WebhookTerminalError(400, "Payload missing required field: url")

    webhook_event: str = payload.get("event", "unknown")
    data: dict = payload.get("data", {})

    webhook_body = {
        "event": webhook_event,
        "data": data,
        "delivered_at": datetime.now(timezone.utc).isoformat(),
    }

    log.info("webhook.attempt", url=url, webhook_event=webhook_event)

    start = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient(
            timeout=settings.WEBHOOK_TIMEOUT,
            max_redirects=settings.WEBHOOK_MAX_REDIRECTS,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                url,
                json=webhook_body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "JobScheduler/1.0",
                    "X-Webhook-Event": webhook_event,
                },
            )
    except httpx.TimeoutException as exc:
        raise WebhookTransientError(f"Request timed out after {settings.WEBHOOK_TIMEOUT}s") from exc
    except httpx.RequestError as exc:
        raise WebhookTransientError(f"Network error: {exc}") from exc

    duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)

    if 200 <= response.status_code < 300:
        log.info(
            "webhook.delivered",
            url=url,
            webhook_event=webhook_event,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return {
            "status_code": response.status_code,
            "response_body": response.text[:500],
            "delivered_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
        }

    if 400 <= response.status_code < 500:
        log.warning(
            "webhook.terminal_failure",
            url=url,
            webhook_event=webhook_event,
            status_code=response.status_code,
        )
        raise WebhookTerminalError(response.status_code, response.text)

    # 5xx
    log.warning(
        "webhook.transient_failure",
        url=url,
        webhook_event=webhook_event,
        status_code=response.status_code,
    )
    raise WebhookTransientError(
        f"Server error {response.status_code}: {response.text[:200]}"
    )
