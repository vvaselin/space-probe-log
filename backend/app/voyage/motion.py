"""区間の式（5章の速度、11章の形）。始点・終点・出発時刻・加速/巡航/減速の時間と速度から、時刻ごとの位置を出す。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from pydantic import BaseModel

from app.voyage.orbits import AU_KM, C_KM_S, Vec3, add, norm, scale, sub

# 太陽からの距離 (AU) と巡航速度 (km/s)。間は対数で補間する。
SPEED_POINTS: tuple[tuple[float, float], ...] = ((1.5, 200.0), (5.0, 1_000.0), (30.0, 3_000.0), (120.0, 0.05 * C_KM_S))
LOCAL_SPEED_KM_S = 180.0  # 惑星系の中（地球から月まで約1時間）
ACCEL_FRACTION = 0.05
MIN_ACCEL_S = 600.0
MAX_ACCEL_S = 86_400.0


def cruise_speed_km_s(r_au: float) -> float:
    if r_au <= SPEED_POINTS[0][0]:
        return SPEED_POINTS[0][1]
    for (r0, v0), (r1, v1) in zip(SPEED_POINTS, SPEED_POINTS[1:]):
        if r_au <= r1:
            return v0 * (v1 / v0) ** (math.log(r_au / r0) / math.log(r1 / r0))
    return SPEED_POINTS[-1][1]


class LegProfile(BaseModel):
    """台形の速度曲線で origin_au から destination_au へ直線で進む。加速と減速は等加速度。"""

    origin_au: Vec3
    destination_au: Vec3
    depart_at: datetime
    accel_s: float
    cruise_s: float
    decel_s: float
    cruise_speed_km_s: float

    @property
    def duration_s(self) -> float:
        return self.accel_s + self.cruise_s + self.decel_s

    @property
    def arrive_at(self) -> datetime:
        return self.depart_at + timedelta(seconds=self.duration_s)

    @property
    def distance_km(self) -> float:
        return norm(sub(self.destination_au, self.origin_au)) * AU_KM

    def travelled_km(self, t: datetime) -> float:
        v, ta, tc, td = self.cruise_speed_km_s, self.accel_s, self.cruise_s, self.decel_s
        tau = (t - self.depart_at).total_seconds()
        if tau <= 0:
            return 0.0
        if tau < ta:
            return 0.5 * v / ta * tau * tau
        s, tau = 0.5 * v * ta, tau - ta
        if tau < tc:
            return s + v * tau
        s, tau = s + v * tc, tau - tc
        if tau < td:
            return s + v * tau - 0.5 * v / td * tau * tau
        return s + 0.5 * v * td

    def speed_at(self, t: datetime) -> float:
        v, ta, tc, td = self.cruise_speed_km_s, self.accel_s, self.cruise_s, self.decel_s
        tau = (t - self.depart_at).total_seconds()
        if tau <= 0 or tau >= self.duration_s:
            return 0.0
        if tau < ta:
            return v * tau / ta
        if tau < ta + tc:
            return v
        return v * (self.duration_s - tau) / td

    def position_at(self, t: datetime) -> Vec3:
        total = self.distance_km
        if total == 0:
            return self.origin_au
        delta = sub(self.destination_au, self.origin_au)
        return add(self.origin_au, scale(delta, min(1.0, self.travelled_km(t) / total)))


def make_profile(origin: Vec3, destination: Vec3, depart_at: datetime, speed_km_s: float) -> LegProfile:
    nominal_s = norm(sub(destination, origin)) * AU_KM / speed_km_s
    ramp_s = min(max(ACCEL_FRACTION * nominal_s, MIN_ACCEL_S), MAX_ACCEL_S, nominal_s)
    return LegProfile(
        origin_au=origin,
        destination_au=destination,
        depart_at=depart_at,
        accel_s=ramp_s,
        cruise_s=nominal_s - ramp_s,
        decel_s=ramp_s,
        cruise_speed_km_s=speed_km_s,
    )
