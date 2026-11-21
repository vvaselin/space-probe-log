"""軌道計算とベクトルの小道具（純関数）。座標は太陽中心・J2000黄道座標、単位はAU。"""

from __future__ import annotations

import math
from datetime import UTC, datetime

Vec3 = tuple[float, float, float]

AU_KM = 149_597_870.7
AU_PER_PC = 206_264.806
C_KM_S = 299_792.458
DAY_S = 86_400.0
J2000 = datetime(2000, 1, 1, 12, 0, tzinfo=UTC)
# shortcut: UTC を TDB とみなす（差は約70秒）。秒単位の精度が要るようになったら換算を入れる。


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec3) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec3) -> Vec3:
    n = norm(a)
    if n == 0:
        raise ValueError("zero-length vector has no direction")
    return scale(a, 1 / n)


def days_since(t: datetime, epoch: datetime = J2000) -> float:
    return (t - epoch).total_seconds() / DAY_S


def solve_kepler(mean_anomaly_rad: float, e: float) -> float:
    """M = E - e sin E を Newton 法で解く。"""
    ecc_anomaly = math.pi if e > 0.8 else mean_anomaly_rad
    for _ in range(50):
        delta = (ecc_anomaly - e * math.sin(ecc_anomaly) - mean_anomaly_rad) / (1 - e * math.cos(ecc_anomaly))
        ecc_anomaly -= delta
        if abs(delta) < 1e-12:
            return ecc_anomaly
    raise ArithmeticError(f"Kepler equation did not converge (M={mean_anomaly_rad}, e={e})")


def kepler_position(a: float, e: float, i_deg: float, node_deg: float, peri_deg: float, mean_anomaly_deg: float) -> Vec3:
    m = math.radians((mean_anomaly_deg + 180.0) % 360.0 - 180.0)
    ecc_anomaly = solve_kepler(m, e)
    xp = a * (math.cos(ecc_anomaly) - e)
    yp = a * math.sqrt(1 - e * e) * math.sin(ecc_anomaly)
    w, o, i = math.radians(peri_deg), math.radians(node_deg), math.radians(i_deg)
    cw, sw, co, so, ci, si = math.cos(w), math.sin(w), math.cos(o), math.sin(o), math.cos(i), math.sin(i)
    return (
        (cw * co - sw * so * ci) * xp + (-sw * co - cw * so * ci) * yp,
        (cw * so + sw * co * ci) * xp + (-sw * so + cw * co * ci) * yp,
        (sw * si) * xp + (cw * si) * yp,
    )


def equatorial_to_ecliptic_unit(ra_deg: float, dec_deg: float) -> Vec3:
    """赤経・赤緯（J2000）の方向を黄道座標の単位ベクトルにする。自転軸（環の向き）に使う。"""
    ra, dec, eps = math.radians(ra_deg), math.radians(dec_deg), math.radians(23.43928)
    x, y, z = math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)
    return (x, math.cos(eps) * y + math.sin(eps) * z, -math.sin(eps) * y + math.cos(eps) * z)
