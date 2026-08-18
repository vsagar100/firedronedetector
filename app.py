from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

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
app = Flask(__name__)


def ensure_runtime_dirs() -> None:
    for path in [REFERENCE_DIR, CURRENT_DIR, RESULTS_DIR, LOG_DIR, CONFIG_DIR]:
        path.mkdir(parents=True, exist_ok=True)
    if not EVENTS_CSV.exists():
        with EVENTS_CSV.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "event_id", "timestamp", "status", "severity", "confidence", "processing_ms",
                "bbox_count", "hotspot_area_percent", "thermal_contrast_index", "latitude", "longitude",
                "altitude_m", "gps_valid", "reference_image", "current_image", "result_image",
                "diff_image", "mask_image", "method"
            ])


def list_images(folder: Path) -> List[Dict[str, Any]]:
    files = []
    if not folder.exists():
        return files
    for item in folder.iterdir():
        if item.is_file() and item.suffix.lower() in ALLOWED_EXT:
            stat = item.stat()
            files.append({
                "name": item.name,
                "size_kb": round(stat.st_size / 1024.0, 2),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "modified_ts": stat.st_mtime,
            })
    return sorted(files, key=lambda x: x["modified_ts"], reverse=True)


def load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if path.exists():
            return {**default, **json.loads(path.read_text(encoding="utf-8"))}
    except Exception:
        return default
    return default


def gps_defaults() -> Dict[str, Any]:
    return load_json(GPS_CONFIG, {
        "latitude": 19.977466,
        "longitude": 73.779865,
        "altitude_m": 18.5,
        "location_label": "Nashik Thermal Surveillance Zone",
    })


def detector_defaults() -> Dict[str, Any]:
    return load_json(DETECTION_CONFIG, {
        "min_area_percent": 0.08,
        "confidence_threshold": 45,
        "min_delta_threshold": 35,
        "heat_gate": 85,
        "morph_kernel": 5,
        "top_contours": 8,
    })


def is_gps_valid(lat: float, lon: float) -> bool:
    return not (abs(lat) < 1e-9 and abs(lon) < 1e-9) and (-90 <= lat <= 90) and (-180 <= lon <= 180)


def media_url(kind: str, filename: str) -> str:
    return f"/media/{kind}/{filename}"


def result_url(filename: str) -> str:
    return f"/static/results/{filename}"


def write_event(event: Dict[str, Any]) -> None:
    ensure_runtime_dirs()
    with EVENTS_CSV.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            event.get("event_id"), event.get("timestamp"), event.get("status"), event.get("severity"),
            event.get("confidence"), event.get("processing_ms"), event.get("bbox_count"),
            event.get("hotspot_area_percent"), event.get("thermal_contrast_index"), event.get("latitude"),
            event.get("longitude"), event.get("altitude_m"), event.get("gps_valid"),
            event.get("reference_image"), event.get("current_image"), event.get("result_image"),
            event.get("diff_image"), event.get("mask_image"), event.get("method"),
        ])


def read_events(limit: int = 12) -> List[Dict[str, Any]]:
    ensure_runtime_dirs()
    if not EVENTS_CSV.exists():
        return []
    with EVENTS_CSV.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.reverse()
    return rows[:limit]


@app.route("/")
def index():
    ensure_runtime_dirs()
    return render_template("index.html")


@app.route("/media/reference/<path:filename>")
def media_reference(filename: str):
    return send_from_directory(REFERENCE_DIR, filename)


@app.route("/media/current/<path:filename>")
def media_current(filename: str):
    return send_from_directory(CURRENT_DIR, filename)


@app.route("/api/health")
def health():
    return jsonify({"status": "online", "service": "Drone Fire Detection Cloud Console", "time": datetime.now().isoformat(timespec="seconds")})


@app.route("/api/images")
def api_images():
    refs = list_images(REFERENCE_DIR)
    currents = list_images(CURRENT_DIR)
    gps = gps_defaults()
    return jsonify({
        "reference": refs,
        "current": currents,
        "default_reference": refs[0]["name"] if refs else None,
        "default_current": currents[0]["name"] if currents else None,
        "gps": gps,
        "detector_config": detector_defaults(),
        "mission": {
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
            "temperature": "31.4 °C",
            "humidity": "42%",
        },
    })


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    ensure_runtime_dirs()
    payload = request.get_json(force=True, silent=True) or {}
    reference_name = payload.get("reference_image")
    current_name = payload.get("current_image")
    refs = list_images(REFERENCE_DIR)
    currents = list_images(CURRENT_DIR)
    if not reference_name and refs:
        reference_name = refs[0]["name"]
    if not current_name and currents:
        current_name = currents[0]["name"]
    if not reference_name or not current_name:
        return jsonify({"ok": False, "error": "Add one reference scene and one current scene in the configured image folders, then refresh."}), 400

    reference_path = (REFERENCE_DIR / reference_name).resolve()
    current_path = (CURRENT_DIR / current_name).resolve()
    if REFERENCE_DIR.resolve() not in reference_path.parents or not reference_path.exists():
        return jsonify({"ok": False, "error": "Invalid reference image."}), 400
    if CURRENT_DIR.resolve() not in current_path.parents or not current_path.exists():
        return jsonify({"ok": False, "error": "Invalid current image."}), 400

    gps_cfg = gps_defaults()
    lat = float(payload.get("latitude", gps_cfg.get("latitude", 0.0)) or 0.0)
    lon = float(payload.get("longitude", gps_cfg.get("longitude", 0.0)) or 0.0)
    alt = float(payload.get("altitude_m", gps_cfg.get("altitude_m", 0.0)) or 0.0)
    gps_valid = is_gps_valid(lat, lon)

    cfg_src = {**detector_defaults(), **(payload.get("detector_config") or {})}
    detector_cfg = DetectorConfig(
        min_area_percent=float(cfg_src.get("min_area_percent", 0.08)),
        confidence_threshold=float(cfg_src.get("confidence_threshold", 45)),
        min_delta_threshold=int(cfg_src.get("min_delta_threshold", 35)),
        heat_gate=int(cfg_src.get("heat_gate", 85)),
        morph_kernel=int(cfg_src.get("morph_kernel", 5)),
        top_contours=int(cfg_src.get("top_contours", 8)),
    )

    event_id = uuid.uuid4().hex[:10]
    timestamp = datetime.now().isoformat(timespec="seconds")
    result_filename = f"annotated_{event_id}.jpg"
    diff_filename = f"difference_{event_id}.jpg"
    mask_filename = f"hotspot_mask_{event_id}.png"
    try:
        result = detect_fire_from_pair(
            reference_path=reference_path,
            current_path=current_path,
            result_path=RESULTS_DIR / result_filename,
            diff_path=RESULTS_DIR / diff_filename,
            mask_path=RESULTS_DIR / mask_filename,
            config=detector_cfg,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    result.update({
        "ok": True,
        "event_id": event_id,
        "timestamp": timestamp,
        "latitude": lat,
        "longitude": lon,
        "altitude_m": alt,
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
            "drone_id": "UAV-FD-07",
            "mission_id": "FD-MSN-2026-0719",
            "zone": "Nashik Thermal Surveillance Zone",
            "payload": "LWIR Thermal + GPS",
            "telemetry": "Encrypted Telemetry",
            "sync_status": "Cloud event synchronized",
        },
    })
    write_event(result)
    return jsonify(result)


@app.route("/api/events")
def api_events():
    return jsonify({"events": read_events(limit=int(request.args.get("limit", 12)))})


@app.route("/api/logs/download")
def download_logs():
    ensure_runtime_dirs()
    return send_from_directory(LOG_DIR, EVENTS_CSV.name, as_attachment=True)


if __name__ == "__main__":
    ensure_runtime_dirs()
    app.run(host="0.0.0.0", port=8080, debug=True)
