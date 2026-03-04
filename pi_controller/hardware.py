import math
import os
import time
from dataclasses import dataclass

from .config import HARDWARE
from .keyboard_input import get_keyboard_input

try:
    from gpiozero import Button, PWMOutputDevice  # type: ignore
    import board  # type: ignore
    import busio  # type: ignore
    import adafruit_ads1x15.ads1115 as ADS  # type: ignore
    from adafruit_ads1x15.analog_in import AnalogIn  # type: ignore
    _PI_HW_AVAILABLE = True
except Exception as e:
    print(f"[hardware] Pi hardware unavailable: {e}")
    Button = None
    PWMOutputDevice = None
    board = None
    busio = None
    ADS = None
    AnalogIn = None
    _PI_HW_AVAILABLE = False

try:
    import neopixel  # type: ignore
    _NEOPIXEL_AVAILABLE = True
except Exception as e:
    print(f"[hardware] NeoPixel unavailable: {e}")
    neopixel = None
    _NEOPIXEL_AVAILABLE = False


@dataclass
class PotSnapshot:
    fan: float
    hue: float
    light: float


class HardwareIO:
    """Pot/button/fan/light interface with simulation fallback."""

    def __init__(self) -> None:
        self._last = PotSnapshot(0.5, 0.5, 0.5)
        self._next_edge_at = time.monotonic() + 5.0
        self._last_button_state = False

        env_flag = os.getenv("BOTANICAL_USE_PI_HARDWARE", "0") == "1"
        self._use_pi = HARDWARE.use_pi_hardware or env_flag
        self._keyboard = get_keyboard_input(
            enabled=os.getenv("BOTANICAL_USE_KEYBOARD", "0") == "1"
        )

        self._fan = None
        self._led = None
        self._button = None
        self._pot_fan = None
        self._pot_hue = None
        self._pot_light = None

        if self._use_pi and _PI_HW_AVAILABLE:
            self._init_pi_hardware()

    def _init_pi_hardware(self) -> None:
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            pots_adc = ADS.ADS1115(i2c)
            pots_adc.gain = 1
            self._pot_fan = AnalogIn(pots_adc, 0)
            self._pot_hue = AnalogIn(pots_adc, 1)
            self._pot_light = AnalogIn(pots_adc, 2)
            print("[hardware] pots OK")
        except Exception as e:
            print(f"[hardware] pots failed: {e}")

        try:
            self._button = Button(HARDWARE.start_button_gpio, pull_up=False)
            print("[hardware] button OK")
        except Exception as e:
            print(f"[hardware] button failed: {e}")

        try:
            self._fan = PWMOutputDevice(HARDWARE.fan_pwm_gpio, frequency=25000)
            print("[hardware] fan OK")
        except Exception as e:
            print(f"[hardware] fan failed: {e}")

        if _NEOPIXEL_AVAILABLE:
            try:
                self._led = neopixel.NeoPixel(board.D18, 1, auto_write=True)
                print("[hardware] LED OK")
            except Exception as e:
                print(f"[hardware] LED failed: {e}")
        else:
            print("[hardware] LED skipped (NeoPixel unavailable)")

    @property
    def last_pots(self) -> PotSnapshot:
        return self._last

    def read_pots(self) -> PotSnapshot:
        if self._keyboard is not None:
            k = self._keyboard.snapshot()
            self._last = PotSnapshot(fan=k.fan, hue=k.hue, light=k.light)
            return self._last

        if self._pot_fan is not None and self._pot_hue is not None and self._pot_light is not None:
            self._last = PotSnapshot(
                fan=self._normalize_ads_voltage(self._pot_fan.voltage),
                hue=self._normalize_ads_voltage(self._pot_hue.voltage),
                light=self._normalize_ads_voltage(self._pot_light.voltage),
            )
            return self._last

        t = time.monotonic()
        self._last = PotSnapshot(
            fan=(math.sin(t * 0.23) + 1.0) * 0.5,
            hue=(math.sin(t * 0.19 + 1.0) + 1.0) * 0.5,
            light=(math.sin(t * 0.27 + 2.0) + 1.0) * 0.5,
        )
        return self._last

    def _normalize_ads_voltage(self, voltage: float) -> float:
        # 3.3V pot rail -> normalized 0..1
        return max(0.0, min(1.0, voltage / 3.3))

    def read_start_button_edge(self) -> bool:
        if self._keyboard is not None:
            return self._keyboard.consume_start_edge()

        if self._button is not None:
            current_pressed = self._button.is_pressed
            is_edge = current_pressed and not self._last_button_state
            self._last_button_state = current_pressed
            return is_edge

        now = time.monotonic()
        if now >= self._next_edge_at:
            self._next_edge_at = now + 20.0
            return True
        return False

    def read_touch_pulse(self) -> bool:
        if self._keyboard is not None:
            return self._keyboard.consume_touch_pulse()
        return False

    def apply_idle_controls(self, pots: PotSnapshot) -> None:
        self.set_fan(pots.fan)
        self.set_light(hue=pots.hue, intensity=pots.light)

    def apply_frozen_controls(self, frozen: PotSnapshot) -> None:
        self.set_fan(frozen.fan)
        self.set_light(hue=frozen.hue, intensity=frozen.light)

    def set_fan(self, value_0_1: float) -> None:
        value_0_1 = max(0.0, min(1.0, value_0_1))
        if self._fan is not None:
            self._fan.value = value_0_1

    def set_light(self, hue: float, intensity: float) -> None:
        hue = max(0.0, min(1.0, hue))
        intensity = max(0.0, min(1.0, intensity))

        if self._led is not None:
            r, g, b = _hsv_to_rgb(hue, 1.0, intensity)
            self._led[0] = (r, g, b)

    def all_off(self) -> None:
        self.set_fan(0.0)
        self.set_light(hue=0.0, intensity=0.0)

    def cleanup(self) -> None:
        if self._fan is not None:
            self._fan.close()
        if self._button is not None:
            self._button.close()
        if self._led is not None:
            self._led.deinit()


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    import colorsys

    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return int(r * 255), int(g * 255), int(b * 255)
