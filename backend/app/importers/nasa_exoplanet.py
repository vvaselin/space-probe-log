from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from app.importers.normalize import MAX_NEARBY_DISTANCE_PC, RealSpaceObject, normalize_exoplanet_row

TAP_SYNC_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

PSCOMP_COLUMNS = [
    "pl_name",
    "hostname",
    "ra",
    "dec",
    "sy_dist",
    "pl_rade",
    "pl_masse",
    "pl_bmassj",
    "pl_orbper",
    "pl_orbsmax",
    "st_teff",
    "st_rad",
    "st_mass",
    "releasedate",
    "rowupdate",
]


async def fetch_nearby_exoplanets(max_distance_pc: float = MAX_NEARBY_DISTANCE_PC) -> list[RealSpaceObject]:
    query = (
        f"select {', '.join(PSCOMP_COLUMNS)} from pscomppars "
        f"where sy_dist <= {max_distance_pc:.6f} and ra is not null and dec is not null and sy_dist is not null "
        "order by sy_dist asc"
    )
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(TAP_SYNC_URL, params={"query": query, "format": "json"})
        response.raise_for_status()
    rows = _extract_rows(response.json())
    return [item for row in rows if (item := normalize_exoplanet_row(row)) is not None]


def build_tap_url(max_distance_pc: float = MAX_NEARBY_DISTANCE_PC) -> str:
    query = (
        f"select {', '.join(PSCOMP_COLUMNS)} from pscomppars "
        f"where sy_dist <= {max_distance_pc:.6f} and ra is not null and dec is not null and sy_dist is not null "
        "order by sy_dist asc"
    )
    return f"{TAP_SYNC_URL}?{urllib.parse.urlencode({'query': query, 'format': 'json'})}"


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []
