import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.importers.jpl_horizons import fetch_solar_system_vectors
from app.importers.nasa_exoplanet import fetch_nearby_exoplanets

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "app" / "data" / "real_space"


async def main() -> None:
    args = parse_args()
    output_dir = Path(args.output) if args.output else DEFAULT_OUTPUT
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.all or args.solar_system:
        solar = await fetch_solar_system_vectors(args.epoch)
        write_dataset(output_dir / "solar_system.json", "jpl_horizons", args.epoch, [item.to_dict() for item in solar])
    if args.all or args.exoplanets:
        exoplanets = await fetch_nearby_exoplanets()
        write_dataset(
            output_dir / "exoplanets_100ly.json",
            "nasa_exoplanet_archive",
            datetime.now(UTC).date().isoformat(),
            [item.to_dict() for item in exoplanets],
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import real solar-system and nearby exoplanet data into JSON caches.")
    parser.add_argument("--solar-system", action="store_true", help="Fetch JPL Horizons vectors for major solar-system bodies.")
    parser.add_argument("--exoplanets", action="store_true", help="Fetch NASA Exoplanet Archive pscomppars entries within 100 ly.")
    parser.add_argument("--all", action="store_true", help="Fetch all supported real-space datasets.")
    parser.add_argument("--epoch", default=datetime.now(UTC).date().isoformat(), help="Horizons epoch, e.g. 2026-06-16.")
    parser.add_argument("--output", default=None, help="Output directory. Defaults to backend/app/data/real_space.")
    args = parser.parse_args()
    if not (args.all or args.solar_system or args.exoplanets):
        args.all = True
    return args


def write_dataset(path: Path, source: str, epoch: str, objects: list[dict]) -> None:
    payload = {
        "schema_version": 1,
        "source": source,
        "source_epoch": epoch,
        "generated_at": datetime.now(UTC).isoformat(),
        "objects": objects,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path} ({len(objects)} objects)")


if __name__ == "__main__":
    asyncio.run(main())
