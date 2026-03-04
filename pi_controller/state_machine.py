import asyncio
import time
from enum import Enum

from .config import RATES, TIMING
from .hardware import HardwareIO, PotSnapshot
from .osc_io import OscBus
from .sensors import SensorPipeline, derive_params


class State(str, Enum):
    IDLE = "idle"
    TALKING = "talking"
    LISTENING = "listening"
    THANKS = "thanks"


class Controller:
    def __init__(self, hw: HardwareIO, osc: OscBus, sensors: SensorPipeline) -> None:
        self.hw = hw
        self.osc = osc
        self.sensors = sensors
        self.state = State.IDLE
        self.frozen = PotSnapshot(0.5, 0.5, 0.5)

    async def run_forever(self) -> None:
        self.osc.state(State.IDLE.value)
        while True:
            await self._run_idle()
            await self._run_talking()
            await self._run_listening()
            await self._run_thanks()

    async def _run_idle(self) -> None:
        self.state = State.IDLE
        self.osc.state(self.state.value)
        print("[controller] state=idle (waiting for start)")
        sleep_s = 1.0 / RATES.idle_poll_hz
        last_state_send = time.monotonic()
        while True:
            pots = self.hw.read_pots()
            self.hw.apply_idle_controls(pots)
            # Mirror live idle knob changes to OSC so visualizer can react immediately.
            self.osc.frozen(fan=pots.fan, hue=pots.hue, light=pots.light)

            self._emit_touch_pulses()

            now = time.monotonic()
            if (now - last_state_send) >= 1.0:
                self.osc.state(self.state.value)
                last_state_send = now

            if self.hw.read_start_button_edge():
                self.frozen = pots
                self.osc.frozen(fan=pots.fan, hue=pots.hue, light=pots.light)
                print(
                    f"[controller] start edge -> frozen fan={pots.fan:.2f} hue={pots.hue:.2f} light={pots.light:.2f}"
                )
                return

            await asyncio.sleep(sleep_s)

    async def _run_talking(self) -> None:
        self.state = State.TALKING
        self.osc.state(self.state.value)
        self.osc.frozen(fan=self.frozen.fan, hue=self.frozen.hue, light=self.frozen.light)
        print("[controller] state=talking")
        self.hw.apply_frozen_controls(self.frozen)
        end_at = time.monotonic() + TIMING.talking_seconds
        while time.monotonic() < end_at:
            await asyncio.sleep(0.03)

    async def _run_listening(self) -> None:
        self.state = State.LISTENING
        self.osc.state(self.state.value)
        self.osc.frozen(fan=self.frozen.fan, hue=self.frozen.hue, light=self.frozen.light)
        print("[controller] state=listening")

        rate = 1.0 / RATES.listening_param_hz
        end_at = time.monotonic() + TIMING.listening_seconds
        last_state_send = time.monotonic()
        while time.monotonic() < end_at:
            frame = self.sensors.read()
            params = derive_params(frame)
            self.osc.sensor(frame.motion, frame.rgb)
            self.osc.params(
                energy=params["energy"],
                density=params["density"],
                sparkle=params["sparkle"],
                hue=params["hue"],
            )
            now = time.monotonic()
            if (now - last_state_send) >= 1.0:
                self.osc.state(self.state.value)
                last_state_send = now
            self.hw.apply_frozen_controls(self.frozen)
            await asyncio.sleep(rate)

    async def _run_thanks(self) -> None:
        self.state = State.THANKS
        self.osc.state(self.state.value)
        self.osc.frozen(fan=self.frozen.fan, hue=self.frozen.hue, light=self.frozen.light)
        print("[controller] state=thanks")
        end_at = time.monotonic() + TIMING.thanks_seconds
        while time.monotonic() < end_at:
            await asyncio.sleep(0.03)
        self.hw.all_off()

    def _emit_touch_pulses(self) -> None:
        sent = 0
        while self.hw.read_touch_pulse():
            self.osc.touch()
            sent += 1
        if sent > 0:
            print(f"[controller] touch pulse -> /sensor/touch x{sent}")
