from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from detector import DetectorConfig, detect_fire_from_pair

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "data" / "non_fire"
CURRENT_DIR = ROOT / "data" / "current"
RESULTS_DIR = ROOT / "static" / "results"
EVENTS_CSV = ROOT / "logs" / "events.csv"

WIDTH = 640
HEIGHT = 480
BASE_LAT = 19.977466
BASE_LON = 73.779865

# 13 deterministic prototype scenarios. Eight contain a fire signature and five are safe scans.
# The generator is intentionally deterministic so library, batch, and event-history records stay reproducible.
SCENARIOS = {
    8: True,
    9: True,
    10: False,
    11: True,
    12: False,
    13: True,
    14: True,
    15: False,
    16: True,
    17: False,
    18: True,
    19: True,
    20: False,
}

EVENT_FIELDS = [
    "event_id",
    "timestamp",
    "status",
    "severity",
    "confidence",
    "processing_ms",
    "bbox_count",
    "hotspot_area_percent",
    "thermal_contrast_index",
    "latitude",
    "longitude",
    "altitude_m",
    "gps_valid",
    "reference_image",
    "current_image",
    "result_image",
    "diff_image",
    "mask_image",
    "method",
]


def smooth_noise(seed: int, scale: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    small = rng.normal(0, 1, (60, 80)).astype(np.float32)
    noise = cv2.resize(small, (WIDTH, HEIGHT), interpolation=cv2.INTER_CUBIC)
    return cv2.GaussianBlur(noise, (0, 0), 7) * scale


def gaussian_blob(cx: int, cy: int, sx: float, sy: float, amplitude: float) -> np.ndarray:
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    return amplitude * np.exp(
        -(((xx - cx) ** 2) / (2 * sx * sx) + ((yy - cy) ** 2) / (2 * sy * sy))
    )


def build_temperature_scene(index: int, fire_present: bool) -> tuple[np.ndarray, np.ndarray]:
    terrain_rng = np.random.default_rng(100 + index)
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]

    baseline = 23.5 + smooth_noise(1000 + index, 2.8)
    baseline += 1.8 * np.sin(xx / 95 + index * 0.4)
    baseline += 1.3 * np.cos(yy / 80 + index * 0.3)

    for _ in range(5):
        cx = int(terrain_rng.integers(40, WIDTH - 40))
        cy = int(terrain_rng.integers(40, HEIGHT - 40))
        baseline += gaussian_blob(
            cx,
            cy,
            int(terrain_rng.integers(35, 90)),
            int(terrain_rng.integers(25, 70)),
            float(terrain_rng.uniform(-3.5, -1.4)),
        )

    object_rng = np.random.default_rng(3000 + index)
    for _ in range(2):
        cx = int(object_rng.integers(60, WIDTH - 60))
        cy = int(object_rng.integers(60, HEIGHT - 60))
        baseline += gaussian_blob(
            cx,
            cy,
            int(object_rng.integers(8, 18)),
            int(object_rng.integers(8, 18)),
            float(object_rng.uniform(8, 15)),
        )

    reference = baseline + smooth_noise(5000 + index, 0.35)
    current = baseline + smooth_noise(6000 + index, 0.45)
    current += 0.35 * np.sin((xx + index * 23) / 120)

    if fire_present:
        fire_rng = np.random.default_rng(7000 + index)
        cx = int(fire_rng.integers(120, WIDTH - 120))
        cy = int(fire_rng.integers(100, HEIGHT - 100))
        sx = int(fire_rng.integers(22, 45))
        sy = int(fire_rng.integers(18, 40))
        amplitude = float(fire_rng.uniform(55, 72))

        current += gaussian_blob(cx, cy, sx, sy, amplitude)
        current += gaussian_blob(
            cx + int(fire_rng.integers(-20, 25)),
            cy + int(fire_rng.integers(-18, 20)),
            sx * 1.7,
            sy * 1.7,
            amplitude * 0.25,
        )
        if index % 3 == 0:
            current += gaussian_blob(
                cx + int(fire_rng.integers(25, 55)),
                cy - int(fire_rng.integers(15, 45)),
                sx * 0.55,
                sy * 0.75,
                amplitude * 0.55,
            )
    else:
        safe_rng = np.random.default_rng(8000 + index)
        if index % 2 == 0:
            current += gaussian_blob(
                int(safe_rng.integers(100, WIDTH - 100)),
                int(safe_rng.integers(80, HEIGHT - 80)),
                14,
                12,
                float(safe_rng.uniform(4, 7)),
            )

    return reference, current


def thermal_palette(temperature: np.ndarray) -> np.ndarray:
    normalized = np.clip((temperature - 15) / (95 - 15) * 255, 0, 255).astype(np.uint8)
    return cv2.applyColorMap(normalized, cv2.COLORMAP_JET)


def read_existing_events() -> list[dict[str, str]]:
    if not EVENTS_CSV.exists():
        return []
    with EVENTS_CSV.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def generate() -> None:
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_CSV.parent.mkdir(parents=True, exist_ok=True)

    preserved_events = [
        row for row in read_existing_events() if not str(row.get("event_id", "")).startswith("demo")
    ]

    demo_events: list[dict[str, object]] = []
    start_time = datetime(2026, 8, 18, 20, 35, 0)

    for position, (index, fire_present) in enumerate(SCENARIOS.items()):
        reference_name = f"base_image {index:02d}.png"
        current_name = f"current_scene {index:02d}.png"
        result_name = f"annotated_demo_{index:02d}.jpg"
        difference_name = f"difference_demo_{index:02d}.jpg"
        mask_name = f"hotspot_mask_demo_{index:02d}.png"

        reference_temp, current_temp = build_temperature_scene(index, fire_present)
        cv2.imwrite(str(REFERENCE_DIR / reference_name), thermal_palette(reference_temp))
        cv2.imwrite(str(CURRENT_DIR / current_name), thermal_palette(current_temp))

        result = detect_fire_from_pair(
            reference_path=REFERENCE_DIR / reference_name,
            current_path=CURRENT_DIR / current_name,
            result_path=RESULTS_DIR / result_name,
            diff_path=RESULTS_DIR / difference_name,
            mask_path=RESULTS_DIR / mask_name,
            config=DetectorConfig(),
        )

        if bool(result["fire_detected"]) != fire_present:
            raise RuntimeError(
                f"Scenario {index:02d} expected fire={fire_present} but detector returned "
                f"fire={result['fire_detected']}."
            )

        latitude = BASE_LAT + (position - 6) * 0.000071 + ((-1) ** position) * 0.000018
        longitude = BASE_LON + (6 - position) * 0.000064 + ((-1) ** (position + 1)) * 0.000022
        altitude = round(15.4 + (position % 6) * 0.9 + (0.3 if position % 2 else 0), 1)
        timestamp = (start_time + timedelta(minutes=9 * position, seconds=17 * position)).isoformat(
            timespec="seconds"
        )

        demo_events.append(
            {
                "event_id": f"demo{index:02d}fd26",
                "timestamp": timestamp,
                "status": result["status"],
                "severity": result["severity"],
                "confidence": result["confidence"],
                "processing_ms": round(180 + (position % 6) * 37.4, 2),
                "bbox_count": result["bbox_count"],
                "hotspot_area_percent": result["hotspot_area_percent"],
                "thermal_contrast_index": result["thermal_contrast_index"],
                "latitude": round(latitude, 6),
                "longitude": round(longitude, 6),
                "altitude_m": altitude,
                "gps_valid": True,
                "reference_image": reference_name,
                "current_image": current_name,
                "result_image": result_name,
                "diff_image": difference_name,
                "mask_image": mask_name,
                "method": result["method"],
            }
        )

    with EVENTS_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        for row in preserved_events:
            writer.writerow({field: row.get(field, "") for field in EVENT_FIELDS})
        for row in demo_events:
            writer.writerow(row)

    fire_count = sum(1 for event in demo_events if event["status"] == "FIRE DETECTED")
    safe_count = len(demo_events) - fire_count
    print(f"Generated {len(demo_events)} thermal pairs: {fire_count} fire, {safe_count} safe.")


if __name__ == "__main__":
    generate()
