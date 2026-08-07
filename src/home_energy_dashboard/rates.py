"""PG&E E-ELEC (NEM3 / NBT) rate estimates and sample valuation.

IMPORTANT: every dollar figure below is an EDITABLE ESTIMATE, not a billed rate.
Tune these against your own PG&E statement and Central Coast Community Energy
(3CE) generation charges. Real NBT export values come from PG&E's Avoided Cost
Calculator (ACC) hourly table and change month to month, so the export curve
here only captures the *shape* (near-zero midday, evening spike). Treat every
number the dashboard derives from this file as an approximation.

Sign convention (normalized once in tesla.normalize_live_status, confirmed
against the Tesla app): grid power > 0 = importing from grid, < 0 = exporting;
battery power > 0 = discharging, < 0 = charging.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo


# --- Import: E-ELEC time-of-use $/kWh (estimates, edit me) -------------------
# E-ELEC TOU windows:
#   Peak         16:00-21:00 (4-9 PM) every day
#   Partial-Peak 15:00-16:00 and 21:00-24:00
#   Off-Peak     all other hours
# Summer = June-September, Winter = October-May.
IMPORT_RATES: dict[str, dict[str, float]] = {
    "summer": {"peak": 0.62, "partial_peak": 0.45, "off_peak": 0.39},
    "winter": {"peak": 0.40, "partial_peak": 0.38, "off_peak": 0.36},
}


def _season(dt_local: datetime) -> str:
    return "summer" if 6 <= dt_local.month <= 9 else "winter"


def _import_period(dt_local: datetime) -> str:
    hour = dt_local.hour
    if 16 <= hour < 21:
        return "peak"
    if hour == 15 or hour >= 21:
        return "partial_peak"
    return "off_peak"


def import_rate(dt_local: datetime) -> float:
    """Estimated retail import price ($/kWh) at a local datetime."""
    return IMPORT_RATES[_season(dt_local)][_import_period(dt_local)]


# --- Export: NBT avoided-cost value $/kWh by hour (estimate, edit me) --------
# 24 entries, index = local hour. Midday solar exports are worth very little;
# summer evening (~7-9 PM) exports can be dramatically more valuable. These are
# placeholder values meant to show the opportunity cost, NOT billed credits.
EXPORT_CURVE_SUMMER: list[float] = [
    0.06, 0.05, 0.05, 0.05, 0.05, 0.06,  # 0-5  overnight
    0.08, 0.09, 0.08, 0.06, 0.05, 0.04,  # 6-11 morning ramp / midday glut
    0.04, 0.04, 0.05, 0.08, 0.20, 0.55,  # 12-17 midday low -> ramp
    0.95, 1.15, 0.70, 0.30, 0.12, 0.08,  # 18-23 evening peak spike
]
EXPORT_CURVE_WINTER: list[float] = [
    0.07, 0.06, 0.06, 0.06, 0.06, 0.07,
    0.09, 0.11, 0.10, 0.08, 0.06, 0.05,
    0.05, 0.05, 0.06, 0.09, 0.18, 0.40,
    0.55, 0.60, 0.40, 0.20, 0.10, 0.08,
]


def export_rate(dt_local: datetime) -> float:
    """Estimated NBT export value ($/kWh) at a local datetime."""
    curve = EXPORT_CURVE_SUMMER if _season(dt_local) == "summer" else EXPORT_CURVE_WINTER
    return curve[dt_local.hour]


# --- Valuation ---------------------------------------------------------------
@dataclass(frozen=True)
class Economics:
    import_cost: float          # $ spent buying from the grid today
    export_credit: float        # $ estimated value of exports today
    net_value: float            # export_credit - import_cost
    imported_kwh: float
    exported_kwh: float
    current_import_rate: float  # $/kWh right now
    current_export_rate: float  # $/kWh right now
    estimated: bool = True

    def as_dict(self) -> dict[str, float | bool]:
        return {
            "import_cost": round(self.import_cost, 2),
            "export_credit": round(self.export_credit, 2),
            "net_value": round(self.net_value, 2),
            "imported_kwh": round(self.imported_kwh, 2),
            "exported_kwh": round(self.exported_kwh, 2),
            "current_import_rate": round(self.current_import_rate, 3),
            "current_export_rate": round(self.current_export_rate, 3),
            "estimated": self.estimated,
        }


# Ignore gaps between samples longer than this (e.g. server was off): a stale
# reading shouldn't be integrated across hours of missing data.
MAX_GAP = timedelta(minutes=15)


def value_samples(
    samples: Iterable[Mapping[str, object]],
    tz: str = "America/Los_Angeles",
    now: datetime | None = None,
) -> Economics:
    """Estimate today's grid economics by integrating stored power samples.

    Each sample needs ``sampled_at`` (ISO-8601 UTC) and signed ``grid_kw``.
    Energy for each interval is the trapezoidal average grid power times the
    interval length; import (grid_kw > 0) is priced at the import rate and
    export (grid_kw < 0) at the NBT export value for that local hour.
    """
    zone = ZoneInfo(tz)
    ordered = sorted(samples, key=lambda s: str(s["sampled_at"]))

    imported_kwh = exported_kwh = 0.0
    import_cost = export_credit = 0.0

    prev_time: datetime | None = None
    prev_grid = 0.0
    for sample in ordered:
        t = datetime.fromisoformat(str(sample["sampled_at"])).astimezone(zone)
        grid = float(sample["grid_kw"])  # type: ignore[arg-type]
        if prev_time is not None:
            gap = t - prev_time
            if timedelta(0) < gap <= MAX_GAP:
                hours = gap.total_seconds() / 3600
                avg = (grid + prev_grid) / 2
                energy = avg * hours  # kWh, signed
                # Price against the interval's midpoint local hour.
                mid = prev_time + gap / 2
                if energy > 0:
                    imported_kwh += energy
                    import_cost += energy * import_rate(mid)
                elif energy < 0:
                    exported_kwh += -energy
                    export_credit += -energy * export_rate(mid)
        prev_time, prev_grid = t, grid

    ref = (now.astimezone(zone) if now else datetime.now(zone))
    return Economics(
        import_cost=import_cost,
        export_credit=export_credit,
        net_value=export_credit - import_cost,
        imported_kwh=imported_kwh,
        exported_kwh=exported_kwh,
        current_import_rate=import_rate(ref),
        current_export_rate=export_rate(ref),
    )
