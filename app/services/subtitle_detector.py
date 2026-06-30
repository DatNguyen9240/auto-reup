import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("SubtitleDetector")


@dataclass
class SubtitleRegion:
    x: int
    y: int
    width: int
    height: int
    source: str
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "source": self.source,
            "confidence": self.confidence,
        }


class SubtitleDetector:
    def __init__(
        self,
        sample_interval_sec: float = 0.75,
        crop_bottom_ratio: float = 0.45,
        padding_x: int = 20,
        padding_y: int = 12,
        max_samples: int = 16,
    ):
        self.sample_interval_sec = sample_interval_sec
        self.crop_bottom_ratio = crop_bottom_ratio
        self.padding_x = padding_x
        self.padding_y = padding_y
        self.max_samples = max_samples

    def detect(self, video_path: Path, metadata: dict, debug_dir: Path) -> Optional[SubtitleRegion]:
        debug_dir.mkdir(parents=True, exist_ok=True)
        frame_dir = debug_dir / "frames"
        frame_dir.mkdir(parents=True, exist_ok=True)

        width = int(metadata.get("width", 0) or 0)
        height = int(metadata.get("height", 0) or 0)
        duration = float(metadata.get("duration", 0) or 0)
        if width <= 0 or height <= 0:
            logger.warning("OCR subtitle detection skipped: invalid video metadata.")
            return None

        samples = self._extract_sample_frames(video_path, frame_dir, duration)
        if not samples:
            logger.warning("OCR subtitle detection failed: no sample frames were extracted.")
            return None

        boxes = []
        crop_y = int(height * (1.0 - self.crop_bottom_ratio))
        for idx, frame_path in enumerate(samples, start=1):
            frame_boxes = self._detect_boxes_in_frame(frame_path, crop_y)
            if frame_boxes:
                boxes.extend(frame_boxes)
            self._write_debug_frame(frame_path, debug_dir / f"frame_{idx:03d}.jpg", frame_boxes)

        if not boxes:
            logger.warning("OCR subtitle detection found no text boxes in sampled bottom area.")
            return None

        region = self._merge_boxes(boxes, width, height)
        with open(debug_dir / "subtitle_region.json", "w", encoding="utf-8") as f:
            json.dump(region.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info(
            "OCR subtitle detection region: "
            f"x={region.x}, y={region.y}, w={region.width}, h={region.height}, confidence={region.confidence:.2f}"
        )
        return region

    def _extract_sample_frames(self, video_path: Path, frame_dir: Path, duration: float) -> list[Path]:
        interval = max(self.sample_interval_sec, 0.25)
        if duration > 0:
            sample_count = max(1, min(self.max_samples, int(math.ceil(duration / interval))))
            fps = sample_count / max(duration, 1.0)
        else:
            fps = 1.0 / interval

        pattern = frame_dir / "sample_%03d.jpg"
        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-i", str(video_path),
            "-vf", f"fps={fps}",
            "-frames:v", str(self.max_samples),
            "-q:v", "3",
            str(pattern),
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except Exception as e:
            logger.warning(f"Failed to extract subtitle detection frames: {e}")
            return []
        return sorted(frame_dir.glob("sample_*.jpg"))

    def _detect_boxes_in_frame(self, frame_path: Path, crop_y: int) -> list[tuple[int, int, int, int]]:
        ocr_boxes = self._detect_with_paddleocr(frame_path, crop_y)
        if ocr_boxes:
            return ocr_boxes
        ocr_boxes = self._detect_with_easyocr(frame_path, crop_y)
        if ocr_boxes:
            return ocr_boxes
        return self._detect_with_heuristic(frame_path, crop_y)

    def _detect_with_paddleocr(self, frame_path: Path, crop_y: int) -> list[tuple[int, int, int, int]]:
        try:
            from paddleocr import PaddleOCR
            import cv2
        except Exception:
            return []

        image = cv2.imread(str(frame_path))
        if image is None:
            return []
        crop = image[crop_y:, :]
        ocr = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)
        result = ocr.ocr(crop, cls=False)
        boxes = []
        for line in result or []:
            for item in line or []:
                points = item[0]
                score = float(item[1][1]) if len(item) > 1 and len(item[1]) > 1 else 0.0
                if score < 0.35:
                    continue
                xs = [int(p[0]) for p in points]
                ys = [int(p[1]) + crop_y for p in points]
                boxes.append((min(xs), min(ys), max(xs), max(ys)))
        return boxes

    def _detect_with_easyocr(self, frame_path: Path, crop_y: int) -> list[tuple[int, int, int, int]]:
        try:
            import easyocr
            import cv2
        except Exception:
            return []

        image = cv2.imread(str(frame_path))
        if image is None:
            return []
        crop = image[crop_y:, :]
        reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
        result = reader.readtext(crop)
        boxes = []
        for points, _text, score in result:
            if float(score) < 0.35:
                continue
            xs = [int(p[0]) for p in points]
            ys = [int(p[1]) + crop_y for p in points]
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
        return boxes

    def _detect_with_heuristic(self, frame_path: Path, crop_y: int) -> list[tuple[int, int, int, int]]:
        try:
            import cv2
            import numpy as np
        except Exception:
            return []

        image = cv2.imread(str(frame_path))
        if image is None:
            return []
        crop = image[crop_y:, :]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        bright = cv2.inRange(gray, 175, 255)
        dark = cv2.inRange(gray, 0, 80)
        mask = cv2.bitwise_or(bright, dark)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (18, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        boxes = []
        crop_h, crop_w = crop.shape[:2]
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            if area < crop_w * crop_h * 0.002:
                continue
            if w < crop_w * 0.12 or h < 12:
                continue
            if h > crop_h * 0.55:
                continue
            boxes.append((x, y + crop_y, x + w, y + h + crop_y))
        return boxes

    def _merge_boxes(self, boxes: list[tuple[int, int, int, int]], width: int, height: int) -> SubtitleRegion:
        y_centers = [(box[1] + box[3]) / 2 for box in boxes]
        median_y = sorted(y_centers)[len(y_centers) // 2]
        filtered = [box for box in boxes if abs(((box[1] + box[3]) / 2) - median_y) < height * 0.18]
        if not filtered:
            filtered = boxes

        x1 = max(0, min(box[0] for box in filtered) - self.padding_x)
        y1 = max(0, min(box[1] for box in filtered) - self.padding_y)
        x2 = min(width, max(box[2] for box in filtered) + self.padding_x)
        y2 = min(height, max(box[3] for box in filtered) + self.padding_y)
        return SubtitleRegion(
            x=x1,
            y=y1,
            width=max(1, x2 - x1),
            height=max(1, y2 - y1),
            source="ocr" if len(filtered) else "heuristic",
            confidence=min(1.0, len(filtered) / max(4, self.max_samples)),
        )

    def _write_debug_frame(self, src: Path, dest: Path, boxes: list[tuple[int, int, int, int]]) -> None:
        try:
            from PIL import Image, ImageDraw
        except Exception:
            try:
                dest.write_bytes(src.read_bytes())
            except Exception:
                pass
            return

        try:
            image = Image.open(src).convert("RGB")
            draw = ImageDraw.Draw(image)
            for x1, y1, x2, y2 in boxes:
                draw.rectangle((x1, y1, x2, y2), outline=(255, 40, 40), width=4)
            image.save(dest, quality=90)
        except Exception as e:
            logger.warning(f"Failed to write subtitle detection debug frame: {e}")
