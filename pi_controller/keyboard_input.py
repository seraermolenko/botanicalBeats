import os
import select
import sys
import termios
import threading
import tty
from dataclasses import dataclass


@dataclass
class KeyboardSnapshot:
    fan: float = 0.5
    hue: float = 0.5
    light: float = 0.5


class KeyboardInput:
    """TTY keyboard controls for non-hardware testing."""

    def __init__(self) -> None:
        self._state = KeyboardSnapshot()
        self._step = 0.05
        self._start_edge = False
        self._touch_pulse = False
        self._lock = threading.Lock()
        self._running = True

        self._stdin_fd = None
        self._stdin_attr = None
        self._thread = None

        if not sys.stdin.isatty():
            print("[keyboard] stdin is not a TTY; keyboard control disabled")
            self._running = False
            return

        self._stdin_fd = sys.stdin.fileno()
        self._stdin_attr = termios.tcgetattr(self._stdin_fd)
        tty.setcbreak(self._stdin_fd)

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._print_help()

    def _print_help(self) -> None:
        print("[keyboard] enabled")
        print("[keyboard] wind: q/a  color(hue): w/s  intensity: e/d")
        print("[keyboard] touch pulse: t  start/send: Enter (or space)  reset: z")
        self._print_state()

    def _run(self) -> None:
        while self._running and self._stdin_fd is not None:
            readable, _, _ = select.select([self._stdin_fd], [], [], 0.05)
            if not readable:
                continue
            ch = os.read(self._stdin_fd, 1)
            if not ch:
                continue
            self._handle_key(ch.decode("utf-8", errors="ignore"))

    def _handle_key(self, ch: str) -> None:
        changed = False
        with self._lock:
            if ch == "q":
                self._state.fan = _clamp01(self._state.fan + self._step)
                changed = True
            elif ch == "a":
                self._state.fan = _clamp01(self._state.fan - self._step)
                changed = True
            elif ch == "w":
                self._state.hue = _clamp01(self._state.hue + self._step)
                changed = True
            elif ch == "s":
                self._state.hue = _clamp01(self._state.hue - self._step)
                changed = True
            elif ch == "e":
                self._state.light = _clamp01(self._state.light + self._step)
                changed = True
            elif ch == "d":
                self._state.light = _clamp01(self._state.light - self._step)
                changed = True
            elif ch == "t":
                self._touch_pulse = True
                print("[keyboard] touch pulse")
            elif ch in ("\n", "\r", " "):
                self._start_edge = True
                print("[keyboard] start edge (commit values)")
            elif ch == "z":
                self._state = KeyboardSnapshot()
                changed = True

        if changed:
            self._print_state()

    def _print_state(self) -> None:
        s = self.snapshot()
        print(
            f"[keyboard] fan={s.fan:.2f} hue={s.hue:.2f} light={s.light:.2f}"
        )

    def snapshot(self) -> KeyboardSnapshot:
        with self._lock:
            return KeyboardSnapshot(
                fan=self._state.fan,
                hue=self._state.hue,
                light=self._state.light,
            )

    def consume_start_edge(self) -> bool:
        with self._lock:
            edge = self._start_edge
            self._start_edge = False
            return edge

    def consume_touch_pulse(self) -> bool:
        with self._lock:
            pulse = self._touch_pulse
            self._touch_pulse = False
            return pulse

    def cleanup(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=0.2)
        if self._stdin_fd is not None and self._stdin_attr is not None:
            termios.tcsetattr(self._stdin_fd, termios.TCSADRAIN, self._stdin_attr)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


_KEYBOARD_INSTANCE: KeyboardInput | None = None


def get_keyboard_input(enabled: bool) -> KeyboardInput | None:
    global _KEYBOARD_INSTANCE
    if not enabled:
        return None
    if _KEYBOARD_INSTANCE is None:
        _KEYBOARD_INSTANCE = KeyboardInput()
    return _KEYBOARD_INSTANCE


def cleanup_keyboard_input() -> None:
    global _KEYBOARD_INSTANCE
    if _KEYBOARD_INSTANCE is not None:
        _KEYBOARD_INSTANCE.cleanup()
        _KEYBOARD_INSTANCE = None
