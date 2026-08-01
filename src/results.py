"""Fetch official iRacing results after a race."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from models import Driver

log = logging.getLogger("uracing.results")

try:
    from iracingdataapi.client import irDataClient

    HAS_DATA = True
except Exception:  # pragma: no cover - optional at import time
    HAS_DATA = False
    irDataClient = None  # type: ignore


def _as_dict(data: Any) -> Dict[str, Any]:
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    # pydantic model
    if hasattr(data, "model_dump"):
        return data.model_dump()
    if hasattr(data, "dict"):
        return data.dict()
    return dict(data)


def fetch_official_summary(
    *,
    email: str,
    password: str,
    subsession_id: int,
    drivers: List[Driver],
    attempts: int = 30,
    delay_seconds: float = 10.0,
) -> Optional[str]:
    """Poll the Data API until results are ready, then format a Discord message."""
    if not HAS_DATA:
        log.info("iracingdataapi not installed; skipping official results")
        return None
    if not (email and password and subsession_id):
        log.info("missing credentials or subsession_id; skipping official results")
        return None

    client = irDataClient(username=email, password=password, silent=True)
    data: Dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        try:
            raw = client.result(subsession_id=int(subsession_id))
            data = _as_dict(raw)
            if data.get("session_results"):
                break
        except Exception as exc:
            log.debug("results attempt %s failed: %s", attempt, exc)
        time.sleep(delay_seconds)
    else:
        log.warning("official results not ready after %s attempts", attempts)
        return None

    sof = data.get("event_strength_of_field")
    if sof is None:
        car_classes = data.get("car_classes") or []
        if car_classes:
            sof = car_classes[0].get("strength_of_field") if isinstance(car_classes[0], dict) else getattr(
                car_classes[0], "strength_of_field", None
            )
    field = data.get("num_drivers") or "?"

    sess_results = data.get("session_results") or []
    race = None
    for s in sess_results:
        sdict = s if isinstance(s, dict) else _as_dict(s)
        name = str(sdict.get("simsession_type_name", "")).lower()
        if name.startswith("race"):
            race = sdict
            break
    if race is None and sess_results:
        last = sess_results[-1]
        race = last if isinstance(last, dict) else _as_dict(last)

    lines = [f"**{field} Cars — SOF {sof if sof is not None else '?'}**"]
    tracked = {d.iracing_id: d for d in drivers if d.iracing_id}

    results = (race or {}).get("results") or []
    for m in results:
        row = m if isinstance(m, dict) else _as_dict(m)
        cid = int(row.get("cust_id", 0) or 0)
        if cid not in tracked:
            continue
        dr = tracked[cid]
        label = f"<@{dr.discord_id}>" if dr.discord_id else dr.name
        new_ir = row.get("newi_rating")
        old_ir = row.get("oldi_rating")
        ir_delta = (new_ir - old_ir) if None not in (new_ir, old_ir) else 0
        new_sr = (row.get("new_sub_level") or 0) / 100.0
        old_sr = (row.get("old_sub_level") or 0) / 100.0
        sr_delta = new_sr - old_sr
        # iRacing positions are often 0-based in the API
        raw_pos = row.get("finish_position")
        if raw_pos is None:
            raw_pos = row.get("position")
        try:
            pos = int(raw_pos) + 1 if raw_pos is not None else "?"
        except (TypeError, ValueError):
            pos = raw_pos if raw_pos is not None else "?"
        incidents = row.get("incidents", 0)
        lines.append(
            f"**{label}** — P{pos}, {incidents}x — {new_ir} ({ir_delta:+}) iRating — "
            f"{new_sr:.2f} ({sr_delta:+.2f}) SR"
        )

    if len(lines) == 1:
        lines.append("_No tracked drivers found in these results._")

    return "\n".join(lines)
