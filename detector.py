from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np


@dataclass
class DetectorConfig:
    min_area_percent: float = 0.08
    confidence_threshold: float = 45.0
    min_delta_threshold: int = 35
    heat_gate: int = 85
    morph_kernel: int = 5
    top_contours: int = 8


def _read_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read image: {path}")
    return image


def _normalize_u8(arr: np.ndarray) -> np.ndarray:
    arr = arr.astype(np.float32)
    mn, mx = float(arr.min()), float(arr.max())
    if mx - mn < 1e-6:
        return np.zeros(arr.shape, dtype=np.uint8)
    return np.clip((arr - mn) * 255.0 / (mx - mn), 0, 255).astype(np.uint8)


def _thermal_hotness_bgr(image: np.ndarray) -> np.ndarray:
    """
    Builds a pseudo-thermal hotness map from colorized thermal images.
    This works for rapid prototyping when raw radiometric temperature matrix is unavailable.
    For final hardware deployment, prefer raw thermal intensity/temperature frames.
    """
    b, g, r = cv2.split(image.astype(np.float32))

    red_minus_blue = _normalize_u8(r - b)
    warm_mix = _normalize_u8((0.65 * r) + (0.35 * g) - (0.25 * b))
    value = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 2]

    hotness = (0.55 * red_minus_blue.astype(np.float32)
               + 0.30 * warm_mix.astype(np.float32)
               + 0.15 * value.astype(np.float32))
    return np.clip(hotness, 0, 255).astype(np.uint8)


def _merge_boxes(boxes: List[Tuple[int, int, int, int]], pad: int = 6) -> List[Tuple[int, int, int, int]]:
    if not boxes:
        return []

    merged: List[Tuple[int, int, int, int]] = []
    boxes = sorted(boxes, key=lambda b: b[0])

    def overlaps(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return not (
            ax + aw + pad < bx or
            bx + bw + pad < ax or
            ay + ah + pad < by or
            by + bh + pad < ay
        )

    for box in boxes:
        has_merged = False
        for i, existing in enumerate(merged):
            if overlaps(existing, box):
                x1 = min(existing[0], box[0])
                y1 = min(existing[1], box[1])
                x2 = max(existing[0] + existing[2], box[0] + box[2])
                y2 = max(existing[1] + existing[3], box[1] + box[3])
                merged[i] = (x1, y1, x2 - x1, y2 - y1)
                has_merged = True
                break
        if not has_merged:
            merged.append(box)

    return merged


def _severity(confidence: float, area_percent: float, max_delta: float) -> str:
    if confidence >= 82 or area_percent >= 4.5 or max_delta >= 210:
        return "CRITICAL"
    if confidence >= 65 or area_percent >= 1.5 or max_delta >= 160:
        return "HIGH"
    if confidence >= 45 or area_percent >= 0.5:
        return "MEDIUM"
    return "LOW"


def detect_fire_from_pair(
    reference_path: Path,
    current_path: Path,
    result_path: Path,
    diff_path: Path,
    mask_path: Path,
    config: DetectorConfig | None = None,
) -> Dict[str, Any]:
    """
    Compares a non-fire reference thermal frame with a current thermal frame.
    Outputs:
      - annotated result image
      - thermal-difference heatmap
      - binary hotspot mask
      - metrics suitable for dashboard/logging
    """
    cfg = config or DetectorConfig()
    t0 = perf_counter()

    reference = _read_image(reference_path)
    current = _read_image(current_path)

    if reference.shape[:2] != current.shape[:2]:
        reference = cv2.resize(reference, (current.shape[1], current.shape[0]), interpolation=cv2.INTER_AREA)

    h, w = current.shape[:2]
    total_px = float(h * w)

    ref_hot = _thermal_hotness_bgr(reference)
    cur_hot = _thermal_hotness_bgr(current)

    positive_delta = cv2.subtract(cur_hot, ref_hot)
    gray_ref = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    gray_cur = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    gray_absdiff = cv2.absdiff(gray_cur, gray_ref)

    combined = cv2.addWeighted(positive_delta, 0.72, gray_absdiff, 0.28, 0)
    combined = cv2.GaussianBlur(combined, (5, 5), 0)

    mean_delta = float(np.mean(combined))
    std_delta = float(np.std(combined))
    p93 = float(np.percentile(combined, 93))
    dynamic_threshold = max(float(cfg.min_delta_threshold), mean_delta + 1.15 * std_delta, p93 * 0.82)

    _, delta_mask = cv2.threshold(combined, dynamic_threshold, 255, cv2.THRESH_BINARY)
    _, heat_mask = cv2.threshold(cur_hot, int(cfg.heat_gate), 255, cv2.THRESH_BINARY)
    mask = cv2.bitwise_and(delta_mask, heat_mask)

    kernel_size = max(3, int(cfg.morph_kernel))
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.dilate(mask, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area_px = max(12, total_px * (float(cfg.min_area_percent) / 100.0))

    boxes: List[Tuple[int, int, int, int]] = []
    contour_areas: List[float] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area_px:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < 4 or bh < 4:
            continue
        boxes.append((x, y, bw, bh))
        contour_areas.append(area)

    boxes = _merge_boxes(boxes)
    boxes = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)[: int(cfg.top_contours)]

    hotspot_area_px = int(cv2.countNonZero(mask))
    hotspot_area_percent = (hotspot_area_px / total_px) * 100.0
    max_delta = float(combined.max())
    thermal_contrast = float(np.mean(cur_hot[mask > 0]) - np.mean(ref_hot[mask > 0])) if hotspot_area_px > 0 else 0.0

    area_score = min(40.0, hotspot_area_percent * 8.0)
    delta_score = min(35.0, max(0.0, (max_delta - dynamic_threshold)) / 255.0 * 70.0)
    contrast_score = min(25.0, max(0.0, thermal_contrast) / 255.0 * 80.0)
    confidence = round(min(100.0, area_score + delta_score + contrast_score), 2)

    fire_detected = bool(boxes and confidence >= float(cfg.confidence_threshold))
    severity = _severity(confidence, hotspot_area_percent, max_delta) if fire_detected else "NORMAL"

    annotated = current.copy()
    overlay = annotated.copy()

    if fire_detected:
        cv2.rectangle(overlay, (0, 0), (w, 58), (0, 0, 80), -1)
        annotated = cv2.addWeighted(overlay, 0.40, annotated, 0.60, 0)

        for idx, (x, y, bw, bh) in enumerate(boxes, start=1):
            cv2.rectangle(annotated, (x, y), (x + bw, y + bh), (0, 0, 255), 3)
            label = f"FIRE #{idx}"
            cv2.putText(annotated, label, (x, max(28, y - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.78, (0, 0, 255), 2, cv2.LINE_AA)

        cv2.putText(annotated, f"FIRE DETECTED | Confidence {confidence:.1f}% | {severity}",
                    (18, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (255, 255, 255), 2, cv2.LINE_AA)
    else:
        cv2.rectangle(overlay, (0, 0), (w, 58), (0, 70, 0), -1)
        annotated = cv2.addWeighted(overlay, 0.40, annotated, 0.60, 0)
        cv2.putText(annotated, f"NO FIRE DETECTED | Confidence {confidence:.1f}%",
                    (18, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (255, 255, 255), 2, cv2.LINE_AA)

    diff_colormap = cv2.applyColorMap(_normalize_u8(combined), cv2.COLORMAP_JET)

    result_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    mask_path.parent.mkdir(parents=True, exist_ok=True)

    cv2.imwrite(str(result_path), annotated)
    cv2.imwrite(str(diff_path), diff_colormap)
    cv2.imwrite(str(mask_path), mask)

    processing_ms = round((perf_counter() - t0) * 1000.0, 2)

    return {
        "fire_detected": fire_detected,
        "status": "FIRE DETECTED" if fire_detected else "NO FIRE",
        "severity": severity,
        "confidence": confidence,
        "processing_ms": processing_ms,
        "image_width": w,
        "image_height": h,
        "bbox_count": len(boxes),
        "boxes": [
            {
                "x": int(x),
                "y": int(y),
                "w": int(bw),
                "h": int(bh),
                "area_percent": round((bw * bh / total_px) * 100.0, 4),
            }
            for x, y, bw, bh in boxes
        ],
        "hotspot_area_px": hotspot_area_px,
        "hotspot_area_percent": round(hotspot_area_percent, 4),
        "thermal_contrast_index": round(thermal_contrast, 3),
        "mean_delta_index": round(mean_delta, 3),
        "max_delta_index": round(max_delta, 3),
        "dynamic_threshold": round(float(dynamic_threshold), 3),
        "method": "Reference-frame thermal hotspot comparison using OpenCV difference, heat-gating, morphology, contour filtering and confidence scoring",
        "note": "Prototype uses pseudo-thermal image comparison. Use raw radiometric thermal data for exact temperature claims.",
    }
