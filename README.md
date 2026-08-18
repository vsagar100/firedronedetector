# FireDrone Detector — Multi-Screen Monitoring Console

A Flask-based rapid prototype for the PhD work **Design and Development of a Secure Edge–Cloud Enabled Multi-Sensor Drone System for Real-Time Fire Detection and Monitoring**.

The interface is presented as a cloud monitoring console, while thermal image evidence is referenced directly from the application filesystem. There is no browser image-upload workflow.

## Application screens

- **Dashboard** — mission overview, platform status, thermal evidence summary and demonstrated capabilities.
- **Fire Detection** — select/compare a baseline non-fire image with a current fire image, run the OpenCV detection pipeline and inspect annotated evidence, difference map and hotspot mask.
- **Evidence Library** — full before/after image listing with side-by-side thermal comparison and one-click analysis.
- **Batch Analysis** — process all detected before/after image pairs and review consolidated detection statistics.
- **Event History** — searchable GPS-tagged event log with detection evidence.
- **Mission & Telemetry** — UAV, thermal payload, edge processor, GPS and telemetry presentation.
- **Settings** — configure GPS defaults and detector thresholds.

## Image folders

```text
data/non_fire/   # baseline / before-fire thermal images
data/current/    # current / fire thermal images
```

The application automatically builds before/after pairs. It first matches image numbers such as `base_image 1.png` with `fire_detected1.jpeg`, then uses scene-name matching and sequence fallback where required.

## Run

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / Raspberry Pi
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:8080
```

## Main routes

```text
/            Dashboard
/detection   Fire Detection
/library     Evidence Library
/batch       Batch Analysis
/events      Event History
/mission     Mission & Telemetry
/settings    System Settings
```

## API

```text
GET  /api/dashboard
GET  /api/images
GET  /api/pairs
POST /api/analyze
POST /api/batch/analyze
GET  /api/events
GET  /api/events/<event_id>
GET  /api/settings
POST /api/settings
```

## Scientific note

The current prototype compares pseudo-colored thermal images. It is suitable for demonstrating relative hotspot/fire-region detection and edge/cloud workflow. Exact temperature claims require raw radiometric thermal sensor data.
