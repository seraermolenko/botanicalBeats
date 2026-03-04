"""
Manual OSC test harness for the visualizer.

Press Enter to send a full "interaction burst" to the visualizer:
- state transitions (idle -> talking -> listening -> idle)
- modulation values (/viz/mod/* and /frozen/*)
- musical cues (/cue/*)

Usage:
  python -m visualizer.test_sender
  python -m visualizer.test_sender --host 127.0.0.1 --port 9001
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from pythonosc.udp_client import SimpleUDPClient


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _send_phase(client: SimpleUDPClient, phase: str, delay_s: float) -> None:
    client.send_message(f"/state/{phase}", [])
    print(f"[test] -> /state/{phase}")
    time.sleep(delay_s)


def _send_burst(client: SimpleUDPClient, listening_s: float, include_thanks: bool) -> None:
    now = time.monotonic()

    frozen_hue = random.random()
    # Keep tester defaults calm to avoid harsh flashes.
    frozen_light = random.uniform(0.30, 0.72)
    frozen_fan = random.uniform(0.12, 0.70)
    mod_hue = (frozen_hue + random.uniform(-0.08, 0.08)) % 1.0
    mod_energy = random.uniform(0.15, 0.55)

    # Idle setup values.
    client.send_message("/frozen/hue", _clamp01(frozen_hue))
    client.send_message("/frozen/light", _clamp01(frozen_light))
    client.send_message("/frozen/fan", _clamp01(frozen_fan))
    client.send_message("/viz/mod/hue", _clamp01(mod_hue))
    client.send_message("/viz/mod/energy", _clamp01(mod_energy))
    print(
        "[test] mod/frozen -> "
        f"hue={frozen_hue:.2f} light={frozen_light:.2f} fan={frozen_fan:.2f} "
        f"mod_hue={mod_hue:.2f} energy={mod_energy:.2f}"
    )

    # 1) talking
    _send_phase(client, "talking", delay_s=0.8)

    # cue burst while talking
    for step in range(10):
        beat = float(step) / 2.0
        bar = 1.0
        vel = random.uniform(0.18, 0.52)
        pulse = random.uniform(0.15, 0.50)
        client.send_message("/viz/audio/pulse", _clamp01(pulse))
        client.send_message("/cue/hit", ["test", beat, bar, _clamp01(vel)])
        if step % 2 == 0:
            client.send_message("/cue/snare", [beat, bar, _clamp01(vel)])
        if step % 3 == 0:
            midi = random.choice([60, 62, 64, 67, 69, 72])
            dur = random.choice([0.25, 0.5, 1.0])
            client.send_message("/cue/note", [midi, dur, beat, bar, _clamp01(vel)])
        time.sleep(0.12)

    client.send_message("/cue/bar", [1.0])
    print("[test] cues -> hit/snare/note/bar")

    # 2) listening
    _send_phase(client, "listening", delay_s=listening_s)

    # 3) optional thanks, then idle
    if include_thanks:
        _send_phase(client, "thanks", delay_s=0.5)
    _send_phase(client, "idle", delay_s=0.0)

    elapsed = time.monotonic() - now
    print(f"[test] burst complete in {elapsed:.2f}s")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual OSC test sender for visualizer")
    parser.add_argument("--host", default="127.0.0.1", help="Visualizer OSC host")
    parser.add_argument("--port", type=int, default=9001, help="Visualizer OSC port")
    parser.add_argument(
        "--listening-seconds",
        type=float,
        default=7.0,
        help="How long to stay in listening state per burst",
    )
    parser.add_argument(
        "--with-thanks",
        action="store_true",
        help="Include the THANKS state (bright screen) before returning to idle",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    client = SimpleUDPClient(args.host, args.port)
    print(f"[test] target visualizer: {args.host}:{args.port}")
    print(
        "[test] press Enter to send a burst "
        f"(listening={args.listening_seconds:.1f}s, thanks={args.with_thanks}), "
        "type 'q' + Enter to quit."
    )

    while True:
        try:
            raw = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\n[test] exiting.")
            return 0

        if raw.strip().lower() in {"q", "quit", "exit"}:
            print("[test] exiting.")
            return 0

        _send_burst(
            client,
            listening_s=max(0.0, args.listening_seconds),
            include_thanks=args.with_thanks,
        )


if __name__ == "__main__":
    sys.exit(main())
