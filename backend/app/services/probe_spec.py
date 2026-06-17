from app.schemas.domain import DriveMode, ProbeSpecification

SPEED_OF_LIGHT_M_S = 299_792_458.0
PROBE_ID = "probe-insomnia-07"
PROBE_LEGACY_IDS = {"probe-aurora"}
PROBE_NAME = "INSOMNIA-07"


def probe_specification() -> ProbeSpecification:
    cruise_speed_fraction_c = 0.8
    max_cruise_speed_fraction_c = 0.8
    cruise_speed_m_s = SPEED_OF_LIGHT_M_S * cruise_speed_fraction_c
    max_speed_m_s = SPEED_OF_LIGHT_M_S * max_cruise_speed_fraction_c
    return ProbeSpecification(
        id=PROBE_ID,
        display_name=PROBE_NAME,
        vessel_type="長寿命恒星間無人探査船",
        length_m=18,
        width_m=6,
        height_m=5,
        deployed_max_width_m=28,
        launch_mass_kg=42_000,
        dry_mass_kg=30_000,
        propellant_mass_kg=4_000,
        repair_resource_feedstock_kg=8_000,
        cruise_speed_fraction_c=cruise_speed_fraction_c,
        cruise_speed_m_s=cruise_speed_m_s,
        cruise_speed_km_s=cruise_speed_m_s / 1000,
        max_cruise_speed_fraction_c=max_cruise_speed_fraction_c,
        max_cruise_speed_m_s=max_speed_m_s,
        max_cruise_speed_km_s=max_speed_m_s / 1000,
        planned_operational_years=500,
        local_drive_mode=DriveMode.conventional,
        interstellar_drive_mode=DriveMode.piano_drive,
        defense="前方多層シールド",
        capabilities=["自己修復", "資源採取", "資源加工", "長期休眠"],
    )
