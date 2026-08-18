# Drone Fire Detection Cloud Console Prototype

This application presents a cloud-style drone fire monitoring console for comparing a reference non-fire thermal image with a current drone thermal image of the same area. It detects abnormal hotspot/fire regions, draws bounding boxes, generates a web alert, displays GPS metadata, saves result evidence, and logs events.

## Image Folders

```text
data/non_fire/   -> reference/non-fire thermal images
data/current/    -> current/test thermal images
```

Supported image formats: jpg, jpeg, png, bmp, tif, tiff, webp.

## Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:8080
```

## GPS

Edit:

```text
config/gps.json
```

The app flags `0,0` as `GPS NOT FIXED`.

## Outputs

```text
static/results/annotated_<event>.jpg
static/results/difference_<event>.jpg
static/results/hotspot_mask_<event>.png
logs/events.csv
```

## Notes

The prototype uses pseudo-thermal image comparison. Exact temperature claims require raw radiometric thermal frames.
