import math
import os
import time
from collections import deque
from dataclasses import dataclass

from .keyboard_input import get_keyboard_input

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    from picamera2 import Picamera2  # type: ignore

    _CAMERA_AVAILABLE = True
except Exception:
    cv2 = None
    np = None
    Picamera2 = None
    _CAMERA_AVAILABLE = False

try:
    import adafruit_tcs34725  # type: ignore
    import board  # type: ignore
    import busio  # type: ignore

    _RGB_SENSOR_AVAILABLE = True
except Exception:
    adafruit_tcs34725 = None
    board = None
    busio = None
    _RGB_SENSOR_AVAILABLE = False


@dataclass
class SensorFrame:
    motion: float
    rgb: tuple[float, float, float]


class CameraMotionDetector:
    """Motion detector using Picamera2 + OpenCV.

    Returns normalized motion [0..1] where 1 corresponds to strongest activity.
    """

    def __init__(self, resolution: tuple[int, int] = (640, 480)) -> None:
        if not _CAMERA_AVAILABLE:
            raise RuntimeError("Camera stack unavailable")

        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(
            main={"size": resolution, "format": "RGB888"}
        )
        self.picam2.configure(config)
        self.picam2.start()
        time.sleep(2)

        self.previous_frame = None
        self.motion_history: deque[float] = deque(maxlen=10)
        self.intensity_thresholds = [0.5, 1.5, 3.0, 5.0, 8.0, float("inf")]

    def _preprocess_frame(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return cv2.GaussianBlur(gray, (21, 21), 0)

    def _calculate_motion_percentage(self, current_frame) -> float:
        if self.previous_frame is None:
            self.previous_frame = current_frame
            return 0.0

        frame_delta = cv2.absdiff(self.previous_frame, current_frame)
        thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        motion_pixels = np.count_nonzero(thresh)
        total_pixels = thresh.shape[0] * thresh.shape[1]
        self.previous_frame = current_frame
        return (motion_pixels / total_pixels) * 100.0

    def _motion_to_intensity(self, motion_score: float) -> int:
        for level, threshold in enumerate(self.intensity_thresholds, start=1):
            if motion_score < threshold:
                return level
        return 6

    def read_motion_normalized(self) -> float:
        frame = self.picam2.capture_array()
        processed = self._preprocess_frame(frame)
        motion_score = self._calculate_motion_percentage(processed)
        intensity_1_to_6 = self._motion_to_intensity(motion_score)
        self.motion_history.append(float(intensity_1_to_6))
        smoothed = float(np.median(list(self.motion_history)))
        return max(0.0, min(1.0, (smoothed - 1.0) / 5.0))

    def cleanup(self) -> None:
        self.picam2.stop()


class SensorPipeline:
    """Reads camera motion + TCS34725 RGB when available, with pot-value fallback."""

    def __init__(self, hw=None) -> None:
        self._hw = hw
        self._keyboard = get_keyboard_input(
            enabled=os.getenv("BOTANICAL_USE_KEYBOARD", "0") == "1"
        )
        self._camera = None
        self._rgb_sensor = None
        if self._keyboard is not None:
            return
        if _CAMERA_AVAILABLE:
            try:
                self._camera = CameraMotionDetector(resolution=(640, 480))
            except Exception:
                self._camera = None
        if _RGB_SENSOR_AVAILABLE:
            try:
                i2c = busio.I2C(board.SCL, board.SDA)
                self._rgb_sensor = adafruit_tcs34725.TCS34725(i2c)
            except Exception:
                self._rgb_sensor = None

    def read(self) -> SensorFrame:
        if self._keyboard is not None:
            k = self._keyboard.snapshot()
            rgb = _hsv01_to_rgb01(k.hue, 1.0, k.light)
            return SensorFrame(motion=0.0, rgb=rgb)

        t = time.monotonic()
        motion = self._read_motion(t)
        r, g, b = self._read_rgb(t)
        return SensorFrame(motion=motion, rgb=(r, g, b))

    def _read_motion(self, t: float) -> float:
        if self._camera is not None:
            try:
                return self._camera.read_motion_normalized()
            except Exception:
                pass
        if self._hw is not None:
            return self._hw.last_pots.fan
        return (math.sin(t * 1.1) + 1.0) * 0.5

    def _read_rgb(self, t: float) -> tuple[float, float, float]:
        if self._rgb_sensor is not None:
            try:
                r, g, b = self._rgb_sensor.color_rgb_bytes
                return r / 255.0, g / 255.0, b / 255.0
            except Exception:
                pass
        if self._hw is not None:
            pots = self._hw.last_pots
            return _hsv01_to_rgb01(pots.hue, 1.0, pots.light)
        return (
            (math.sin(t * 0.7) + 1.0) * 0.5,
            (math.sin(t * 0.9 + 1.0) + 1.0) * 0.5,
            (math.sin(t * 1.3 + 2.0) + 1.0) * 0.5,
        )

    def cleanup(self) -> None:
        if self._camera is not None:
            self._camera.cleanup()


def derive_params(frame: SensorFrame) -> dict[str, float]:
    r, g, b = frame.rgb
    chroma = max(frame.rgb) - min(frame.rgb)
    energy = max(0.0, min(1.0, 0.6 * frame.motion + 0.4 * chroma))
    density = max(0.0, min(1.0, 0.5 * energy + 0.5 * g))
    sparkle = max(0.0, min(1.0, 0.5 * r + 0.5 * b))
    hue = r
    return {
        "energy": energy,
        "density": density,
        "sparkle": sparkle,
        "hue": hue,
    }


def _hsv01_to_rgb01(h: float, s: float, v: float) -> tuple[float, float, float]:
    import colorsys

    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return r, g, b
