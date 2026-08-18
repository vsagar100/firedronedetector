from __future__ import annotations

import csv
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request, send_from_directory

from detector import DetectorConfig, detect_fire_from_pair

APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = APP_ROOT / "data"
REFERENCE_DIR = DATA_DIR / "non_fire"
CURRENT_DIR = DATA_DIR / "current"
RESULTS_DIR = APP_ROOT / "static" / "results"
LOG_DIR = APP_ROOT / "logs"
CONFIG_DIR = APP_ROOT / "config"
GPS_CONFIG = CONFIG_DIR / "gps.json"
DETECTION_CONFIG = CONFIG_DIR / "detection_config.json"
EVENTS_CSV = LOG_DIR / "events.csv"

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

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

MISSION = {
    "drone_id": "UAV-FD-07",
    "mission_id": "FD-MSN-2026-0719",
    "operator": "Command Center",
    "zone": "Nashik Thermal Surveillance Zone",
    "link": "Encrypted Telemetry",
    "camera": "LWIR Thermal Payload",
    "cloud_node": "Edge–Cloud Sync Active",
    "battery": 82,
    "signal": 94,
    "flight_mode": "Auto Surveillance",
    "wind": "6.2 km/h",
    "ambient_temperature": "31.4 °C",
    "humidity": "42%",
    "edge_node": "Raspberry Pi 4",
    "flight_controller": "Pixhawk Cube",
    "gps_module": "Here3+ GNSS",
}

app = Flask(__name__)


def ensure_runtime_dirs() -> None:
    for path in [REFERENCE_DIR, CURRENT_DIR, RESULTS_DIR, LOG_DIR, CONFIG_DIR]:
        path.mkdir(parents=True, exist_ok=True)

    if not EVENTS_CSV.exists():
        with EVENTS_CSV.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=EVENT_FIELDS).writeheader()


def load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if path.exists():
            return {**default, **json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, ValueError, TypeError):
        pass
    return default.copy()


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp_path.replace(path)


def gps_defaults() -> Dict[str, Any]:
    return load_json(
        GPS_CONFIG,
        {
            "latitude": 19.977466,
            "longitude": 73.779865,
            "altitude_m": 18.5,
            "location_label": "Nashik Thermal Surveillance Zone",
        },
    )


def detector_defaults() -> Dict[str, Any]:
    return load_json(
        DETECTION_CONFIG,
        {
            "min_area_percent": 0.08,
            "confidence_threshold": 45,
            "min_delta_threshold": 35,
            "heat_gate": 85,
            "morph_kernel": 5,
            "top_contours": 8,
        },
    )


def is_gps_valid(latitude: float, longitude: float) -> bool:
    return (
        not (abs(latitude) < 1e-9 and abs(longitude) < 1e-9)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def natural_key(value: str) -> List[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def first_number(value: str) -> Optional[int]:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else None


def media_url(kind: str, filename: str) -> str:
    return f"/media/{kind}/{filename}"


def result_url(filename: str) -> str:
    return f"/static/results/{filename}"


def list_images(folder: Path, kind: str) -> List[Dict[str, Any]]:
    ensure_runtime_dirs()
    files: List[Dict[str, Any]] = []
    for item in folder.iterdir():
        if not item.is_file() or item.suffix.lower() not in ALLOWED_EXT:
            continue
        stat = item.stat()
        files.append(
            {
                "name": item.name,
                "size_kb": round(stat.st_size / 1024.0, 2),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "modified_ts": stat.st_mtime,
                "url": media_url(kind, item.name),
            }
        )
    return sorted(files, key=lambda entry: natural_key(entry["name"]))


def _pair_record(
    reference: Dict[str, Any],
    current: Dict[str, Any],
    pairing: str,
    index: int,
) -> Dict[str, Any]:
    gps = gps_defaults()
    return {
        "id": f"pair-{index:02d}",
        "label": f"Thermal Comparison {index:02d}",
        "pairing": pairing,
        "before": reference,
        "after": current,
        "latitude": gps["latitude"],
        "longitude": gps["longitude"],
        "altitude_m": gps["altitude_m"],
    }


def build_image_pairs() -> List[Dict[str, Any]]:
    references = list_images(REFERENCE_DIR, "reference")
    currents = list_images(CURRENT_DIR, "current")

    refs_by_number: Dict[int, Dict[str, Any]] = {}
    for item in references:
        number = first_number(item["name"])
        if number is not None:
            refs_by_number.setdefault(number, item)

    used_references: set[str] = set()
    used_currents: set[str] = set()
    pairs: List[Dict[str, Any]] = []

    scene_ref = next((item for item in references if "reference_scene" in item["name"].lower()), None)
    scene_cur = next((item for item in currents if "fire_detected_scene" in item["name"].lower()), None)
    if scene_ref and scene_cur:
        pairs.append(_pair_record(scene_ref, scene_cur, "scene-match", len(pairs) + 1))
        used_references.add(scene_ref["name"])
        used_currents.add(scene_cur["name"])

    for current in currents:
        if current["name"] in used_currents:
            continue
        number = first_number(current["name"])
        reference = refs_by_number.get(number) if number is not None else None
        if reference and reference["name"] not in used_references:
            pairs.append(_pair_record(reference, current, "number-match", len(pairs) + 1))
            used_references.add(reference["name"])
            used_currents.add(current["name"])

    remaining_refs = [item for item in references if item["name"] not in used_references]
    remaining_currents = [item for item in currents if item["name"] not in used_currents]
    for reference, current in zip(remaining_refs, remaining_currents):
        pairs.append(_pair_record(reference, current, "sequence-pair", len(pairs) + 1))

    return pairs


def write_event(event: Dict[str, Any]) -> None:
    ensure_runtime_dirs()
    row = {field: event.get(field, "") for field in EVENT_FIELDS}
    with EVENTS_CSV.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=EVENT_FIELDS).writerow(row)


def enrich_event(event: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(event)
    reference_name = event.get("reference_image")
    current_name = event.get("current_image")
    result_name = event.get("result_image")
    diff_name = event.get("diff_image")
    mask_name = event.get("mask_image")

    if reference_name:
        enriched["reference_url"] = media_url("reference", reference_name)
    if current_name:
        enriched["current_url"] = media_url("current", current_name)
    if result_name:
        enriched["result_url"] = result_url(result_name)
    if diff_name:
        enriched["diff_url"] = result_url(diff_name)
    if mask_name:
        enriched["mask_url"] = result_url(mask_name)
    return enriched


def read_events(limit: int = 50) -> List[Dict[str, Any]]:
    ensure_runtime_dirs()
    with EVENTS_CSV.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows.reverse()
    return [enrich_event(row) for row in rows[:limit]]


def find_pair(pair_id: str) -> Optional[Dict[str, Any]]:
    return next((pair for pair in build_image_pairs() if pair["id"] == pair_id), None)


def resolve_image(folder: Path, filename: str) -> Path:
    candidate = (folder / filename).resolve()
    if folder.resolve() not in candidate.parents or not candidate.exists():
        raise ValueError(f"Image not found: {filename}")
    return candidate


def run_analysis(
    reference_name: str,
    current_name: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = payload or {}
    reference_path = resolve_image(REFERENCE_DIR, reference_name)
    current_path = resolve_image(CURRENT_DIR, current_name)

    gps = gps_defaults()
    latitude = float(payload.get("latitude", gps["latitude"]) or 0.0)
    longitude = float(payload.get("longitude", gps["longitude"]) or 0.0)
    altitude_m = float(payload.get("altitude_m", gps["altitude_m"]) or 0.0)
    gps_valid = is_gps_valid(latitude, longitude)

    detector_settings = {**detector_defaults(), **(payload.get("detector_config") or {})}
    detector_config = DetectorConfig(
        min_area_percent=float(detector_settings["min_area_percent"]),
        confidence_threshold=float(detector_settings["confidence_threshold"]),
        min_delta_threshold=int(detector_settings["min_delta_threshold"]),
        heat_gate=int(detector_settings["heat_gate"]),
        morph_kernel=int(detector_settings["morph_kernel"]),
        top_contours=int(detector_settings["top_contours"]),
    )

    event_id = uuid.uuid4().hex[:10]
    timestamp = datetime.now().isoformat(timespec="seconds")
    result_filename = f"annotated_{event_id}.jpg"
    diff_filename = f"difference_{event_id}.jpg"
    mask_filename = f"hotspot_mask_{event_id}.png"

    result = detect_fire_from_pair(
        reference_path=reference_path,
        current_path=current_path,
        result_path=RESULTS_DIR / result_filename,
        diff_path=RESULTS_DIR / diff_filename,
        mask_path=RESULTS_DIR / mask_filename,
        config=detector_config,
    )

    result.update(
        {
            "ok": True,
            "event_id": event_id,
            "timestamp": timestamp,
            "latitude": latitude,
            "longitude": longitude,
            "altitude_m": altitude_m,
            "gps_valid": gps_valid,
            "gps_message": "GPS LOCK VALID" if gps_valid else "GPS NOT FIXED",
            "reference_image": reference_name,
            "current_image": current_name,
            "reference_url": media_url("reference", reference_name),
            "current_url": media_url("current", current_name),
            "result_image": result_filename,
            "diff_image": diff_filename,
            "mask_image": mask_filename,
            "result_url": result_url(result_filename),
            "diff_url": result_url(diff_filename),
            "mask_url": result_url(mask_filename),
            "mission": {
                "drone_id": MISSION["drone_id"],
                "mission_id": MISSION["mission_id"],
                "zone": MISSION["zone"],
                "payload": "LWIR Thermal + GPS",
                "telemetry": MISSION["link"],
                "sync_status": "Cloud event synchronized",
            },
        }
    )
    write_event(result)
    return result


@app.route("/")
def dashboard():
    ensure_runtime_dirs()
    return render_template("dashboard.html", page="dashboard", page_title="Dashboard")


@app.route("/detection")
def detection_page():
    return render_template("detection.html", page="detection", page_title="Fire Detection")


@app.route("/library")
def library_page():
    return render_template("library.html", page="library", page_title="Evidence Library")


@app.route("/batch")
def batch_page():
    return render_template("batch.html", page="batch", page_title="Batch Analysis")


@app.route("/events")
def events_page():
    return render_template("events.html", page="events", page_title="Event History")


@app.route("/mission")
def mission_page():
    return render_template("mission.html", page="mission", page_title="Mission & Telemetry")


@app.route("/settings")
def settings_page():
    return render_template("settings.html", page="settings", page_title="System Settings")


@app.route("/media/reference/<path:filename>")
def media_reference(filename: str):
    return send_from_directory(REFERENCE_DIR, filename)


@app.route("/media/current/<path:filename>")
def media_current(filename: str):
    return send_from_directory(CURRENT_DIR, filename)


@app.route("/api/health")
def health():
    return jsonify(
        {
            "status": "online",
            "service": "Drone Fire Detection Cloud Console",
            "time": datetime.now().isoformat(timespec="seconds"),
        }
    )


@app.route("/api/dashboard")
def api_dashboard():
    pairs = build_image_pairs()
    events = read_events(limit=50)
    fire_events = [event for event in events if "FIRE DETECTED" in str(event.get("status", ""))]
    return jsonify(
        {
            "mission": MISSION,
            "gps": gps_defaults(),
            "pairs": pairs,
            "stats": {
                "image_pairs": len(pairs),
                "events": len(events),
                "fire_events": len(fire_events),
                "system_health": 98,
            },
            "telemetry_series": {
                "battery": [93, 91, 89, 87, 85, 84, 82],
                "signal": [91, 94, 93, 95, 94, 96, 94],
                "altitude": [10.5, 12.2, 15.0, 18.5, 17.8, 16.2, 18.5],
            },
            "capabilities": [
                "Thermal frame acquisition",
                "Reference-frame comparison",
                "Onboard/edge fire detection",
                "GPS-tagged alerting",
                "Event evidence capture",
                "Edge–cloud synchronization",
            ],
        }
    )


@app.route("/api/images")
def api_images():
    pairs = build_image_pairs()
    references = list_images(REFERENCE_DIR, "reference")
    currents = list_images(CURRENT_DIR, "current")
    return jsonify(
        {
            "reference": references,
            "current": currents,
            "pairs": pairs,
            "default_reference": pairs[0]["before"]["name"] if pairs else (references[0]["name"] if references else None),
            "default_current": pairs[0]["after"]["name"] if pairs else (currents[0]["name"] if currents else None),
            "gps": gps_defaults(),
            "detector_config": detector_defaults(),
            "mission": MISSION,
        }
    )


@app.route("/api/pairs")
def api_pairs():
    return jsonify({"pairs": build_image_pairs()})


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    payload = request.get_json(force=True, silent=True) or {}
    reference_name = payload.get("reference_image")
    current_name = payload.get("current_image")
    pair_id = payload.get("pair_id")

    if pair_id and (not reference_name or not current_name):
        pair = find_pair(pair_id)
        if pair:
            reference_name = pair["before"]["name"]
            current_name = pair["after"]["name"]

    if not reference_name or not current_name:
        pairs = build_image_pairs()
        if pairs:
            reference_name = pairs[0]["before"]["name"]
            current_name = pairs[0]["after"]["name"]

    if not reference_name or not current_name:
        return jsonify({"ok": False, "error": "No thermal comparison pair is available."}), 400

    try:
        return jsonify(run_analysis(reference_name, current_name, payload))
    except (ValueError, OSError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Analysis failed: {exc}"}), 500


@app.route("/api/batch/analyze", methods=["POST"])
def api_batch_analyze():
    payload = request.get_json(force=True, silent=True) or {}
    pair_ids = payload.get("pair_ids") or [pair["id"] for pair in build_image_pairs()]
    pair_map = {pair["id"]: pair for pair in build_image_pairs()}

    results = []
    for pair_id in pair_ids:
        pair = pair_map.get(pair_id)
        if not pair:
            results.append({"pair_id": pair_id, "ok": False, "error": "Pair not found"})
            continue
        try:
            result = run_analysis(pair["before"]["name"], pair["after"]["name"], payload)
            result["pair_id"] = pair_id
            result["pair_label"] = pair["label"]
            results.append(result)
        except Exception as exc:
            results.append({"pair_id": pair_id, "pair_label": pair["label"], "ok": False, "error": str(exc)})

    successful = [result for result in results if result.get("ok")]
    fire_count = sum(1 for result in successful if result.get("fire_detected"))
    average_confidence = (
        round(sum(float(result.get("confidence", 0)) for result in successful) / len(successful), 2)
        if successful
        else 0
    )
    total_latency = round(sum(float(result.get("processing_ms", 0)) for result in successful), 2)

    return jsonify(
        {
            "ok": True,
            "results": results,
            "summary": {
                "processed": len(successful),
                "requested": len(pair_ids),
                "fire_count": fire_count,
                "average_confidence": average_confidence,
                "total_processing_ms": total_latency,
            },
        }
    )


@app.route("/api/events")
def api_events():
    limit = max(1, min(int(request.args.get("limit", 50)), 500))
    severity = request.args.get("severity")
    events = read_events(limit=limit)
    if severity:
        events = [event for event in events if str(event.get("severity", "")).upper() == severity.upper()]
    return jsonify({"events": events})


@app.route("/api/events/<event_id>")
def api_event_detail(event_id: str):
    event = next((item for item in read_events(limit=500) if item.get("event_id") == event_id), None)
    if not event:
        return jsonify({"ok": False, "error": "Event not found"}), 404
    return jsonify({"ok": True, "event": event})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        return jsonify({"gps": gps_defaults(), "detector": detector_defaults(), "mission": MISSION})

    payload = request.get_json(force=True, silent=True) or {}
    gps_payload = payload.get("gps") or {}
    detector_payload = payload.get("detector") or {}

    gps = {
        **gps_defaults(),
        **{key: gps_payload[key] for key in ["latitude", "longitude", "altitude_m", "location_label"] if key in gps_payload},
    }
    detector = {
        **detector_defaults(),
        **{
            key: detector_payload[key]
            for key in [
                "min_area_percent",
                "confidence_threshold",
                "min_delta_threshold",
                "heat_gate",
                "morph_kernel",
                "top_contours",
            ]
            if key in detector_payload
        },
    }

    gps["latitude"] = float(gps["latitude"])
    gps["longitude"] = float(gps["longitude"])
    gps["altitude_m"] = float(gps["altitude_m"])

    detector["min_area_percent"] = float(detector["min_area_percent"])
    detector["confidence_threshold"] = float(detector["confidence_threshold"])
    detector["min_delta_threshold"] = int(detector["min_delta_threshold"])
    detector["heat_gate"] = int(detector["heat_gate"])
    detector["morph_kernel"] = int(detector["morph_kernel"])
    detector["top_contours"] = int(detector["top_contours"])

    write_json(GPS_CONFIG, gps)
    write_json(DETECTION_CONFIG, detector)
    return jsonify({"ok": True, "gps": gps, "detector": detector})


@app.route("/api/logs/download")
def download_logs():
    ensure_runtime_dirs()
    return send_from_directory(LOG_DIR, EVENTS_CSV.name, as_attachment=True)


if __name__ == "__main__":
    ensure_runtime_dirs()
    app.run(host="0.0.0.0", port=8080, debug=True)
