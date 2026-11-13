"""Push notifications (ntfy.sh) for battery-full alerts.

ntfy needs no account: publish to a topic URL and subscribe to the same topic
name in the ntfy phone app. Pick a long, hard-to-guess topic — public topics
are readable by anyone who knows the name.
"""

from __future__ import annotations

import logging

import httpx

from .config import Settings


logger = logging.getLogger("home_energy_dashboard")


def rising_edge(
    soc: float, armed: bool, threshold_pct: float, rearm_pct: float
) -> tuple[bool, bool]:
    """Decide whether to fire a one-shot SOC alert (pure, for easy testing).

    Returns ``(should_notify, new_armed)``. The alert fires once on the rising
    edge up through ``threshold_pct`` and does not fire again until SOC has
    dropped back below ``rearm_pct`` — so a battery sitting above the threshold
    produces a single alert, and it re-arms on the next discharge. Used for both
    the "full" (≈100%) and the "safe to plug in" (≈50%) notifications.
    """
    if soc < rearm_pct:
        return (False, True)          # discharged enough — re-arm
    if armed and soc >= threshold_pct:
        return (True, False)          # crossed threshold while armed — fire, disarm
    return (False, armed)             # no change


async def send_ntfy(
    settings: Settings, title: str, message: str, tags: str = "battery"
) -> None:
    """Best-effort push to the configured ntfy topic. No-op if unconfigured."""
    if not settings.ntfy_topic:
        return
    url = f"{settings.ntfy_server.rstrip('/')}/{settings.ntfy_topic}"
    headers = {"Title": title, "Tags": tags, "Priority": "default"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url, content=message.encode("utf-8"), headers=headers
            )
            response.raise_for_status()
    except Exception as exc:  # notifications must never break the sampler
        logger.warning("ntfy notification failed: %s", exc)
