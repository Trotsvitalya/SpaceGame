"""Extract and chroma-key the supplied Tiger clip to transparent PNG frames.

Optional tool: requires OpenCV (``python -m pip install opencv-python``).
The original MP4 is read only. Green is keyed by HSV hue and saturation, with
a soft edge and edge-only spill suppression to retain tiger color detail.
"""

from __future__ import annotations

import argparse
import json
import os

import cv2
import numpy as np


def key_frame(frame_bgr, hue_center=60, hue_tolerance=24,
              saturation_floor=35, softness=22, spill=0.38):
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    hue_distance = np.abs(hsv[:, :, 0] - float(hue_center))
    hue_distance = np.minimum(hue_distance, 180.0 - hue_distance)
    chroma = np.clip((hsv[:, :, 1] - saturation_floor) / 130.0, 0.0, 1.0)
    green_likelihood = np.clip((hue_tolerance + softness - hue_distance) /
                               max(1.0, softness), 0.0, 1.0) * chroma
    alpha = (1.0 - green_likelihood) * 255.0
    # Defringe partially transparent boundary pixels toward neutral luminance.
    edge = (alpha > 0) & (alpha < 250) & (green_likelihood > 0)
    bgr = frame_bgr.astype(np.float32)
    green_excess = np.maximum(0.0, bgr[:, :, 1] -
                              np.maximum(bgr[:, :, 0], bgr[:, :, 2]))
    for channel in (0, 2):
        bgr[:, :, channel] += green_excess * spill * edge
    bgr[:, :, 1] -= green_excess * spill * edge
    rgb = cv2.cvtColor(np.clip(bgr, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)
    return np.dstack((rgb, alpha.astype(np.uint8)))


def extract(source, output, hue_center=60, hue_tolerance=24,
            saturation_floor=35, softness=22, spill=0.38,
            max_width=640, contains_title=False, last_clean_frame=None):
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise RuntimeError(f"Could not decode video: {source}")
    os.makedirs(output, exist_ok=True)
    count = 0
    fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = 2 if fps > 45 else 1
    output_fps = fps / step
    source_index = 0
    frame_boxes = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if source_index % step:
                source_index += 1
                continue
            source_index += 1
            if last_clean_frame is not None and count > last_clean_frame:
                break
            keyed = key_frame(frame, hue_center, hue_tolerance,
                              saturation_floor, softness, spill)
            if keyed.shape[1] > max_width:
                out_h = max(1, round(keyed.shape[0] * max_width / keyed.shape[1]))
                keyed = cv2.resize(keyed, (max_width, out_h),
                                   interpolation=cv2.INTER_AREA)
            alpha_mask = np.where(keyed[:, :, 3] > 2, 255, 0).astype(np.uint8)
            bounds = cv2.findNonZero(alpha_mask)
            if bounds is None:
                x, y, w, h = 0, 0, keyed.shape[1], keyed.shape[0]
            else:
                x, y, w, h = cv2.boundingRect(bounds)
                pad = 3
                x0, y0 = max(0, x-pad), max(0, y-pad)
                x1 = min(keyed.shape[1], x+w+pad)
                y1 = min(keyed.shape[0], y+h+pad)
                x, y, w, h = x0, y0, x1-x0, y1-y0
                keyed = keyed[y0:y1, x0:x1]
            frame_boxes.append([x, y, w, h])
            if not cv2.imwrite(os.path.join(output, f"{count:06d}.png"),
                               cv2.cvtColor(keyed, cv2.COLOR_RGBA2BGRA),
                               [cv2.IMWRITE_PNG_COMPRESSION, 8]):
                raise RuntimeError(f"Could not write frame {count}")
            count += 1
    finally:
        capture.release()
    if not count:
        raise RuntimeError("Video decoded no frames")
    with open(os.path.join(output, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"fps": output_fps, "source_fps": fps,
                   "width": width, "height": height,
                   "frame_width": min(width, max_width),
                   "frame_height": round(height * min(width, max_width) / width),
                   "frames": count, "duration": count / output_fps,
                   "contains_title": bool(contains_title and last_clean_frame is None),
                   "source_contains_title": bool(contains_title),
                   "frame_boxes": frame_boxes}, f, indent=2)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", default="assets/video/tiger.mp4")
    parser.add_argument("--output", default="assets/video/tiger_frames")
    parser.add_argument("--hue", type=int, default=60)
    parser.add_argument("--tolerance", type=int, default=24)
    parser.add_argument("--saturation", type=int, default=35)
    parser.add_argument("--softness", type=int, default=22)
    parser.add_argument("--spill", type=float, default=.38)
    parser.add_argument("--max-width", type=int, default=640)
    parser.add_argument("--contains-title", action="store_true",
                        help="The supplied video already contains 虎虎生威")
    parser.add_argument("--last-clean-frame", type=int, default=None,
                        help="Last extracted frame before an embedded title appears")
    args = parser.parse_args()
    count = extract(args.source, args.output, args.hue, args.tolerance,
                    args.saturation, args.softness, args.spill,
                    args.max_width, args.contains_title,
                    args.last_clean_frame)
    print(f"Wrote {count} transparent PNG frames to {args.output}")


if __name__ == "__main__":
    main()
