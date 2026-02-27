import asyncio
import math
import time
from dataclasses import dataclass

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer

try:
    import pygame

    _HAS_PYGAME = True
except Exception:
    pygame = None
    _HAS_PYGAME = False


@dataclass
class VizState:
    phase: str = "idle"
    hue: float = 0.5
    energy: float = 0.0
    last_hit_at: float = 0.0


state = VizState()


def _set_phase(phase: str):
    def handler(_address, *_args):
        state.phase = phase
        print(f"[viz] phase -> {phase}")

    return handler


def _mod_hue(_address, value):
    state.hue = float(value)


def _mod_energy(_address, value):
    state.energy = float(value)


def _cue_snare(_address, beat, bar, vel):
    state.last_hit_at = time.monotonic()
    print(f"[viz] cue snare beat={beat} bar={bar} vel={vel}")


def _cue_hit(_address, name, beat, bar, vel):
    state.last_hit_at = time.monotonic()
    print(f"[viz] cue hit name={name} beat={beat} bar={bar} vel={vel}")


def _cue_note(_address, midi, dur, beat, bar, vel):
    state.last_hit_at = time.monotonic()
    print(f"[viz] cue note midi={midi} dur={dur} beat={beat} bar={bar} vel={vel}")


def _draw_text_center(screen, text: str, font, y_offset: int = 0) -> None:
    if font is None:
        return
    surf = font.render(text, True, (240, 240, 240))
    rect = surf.get_rect(center=(screen.get_width() // 2, screen.get_height() // 2 + y_offset))
    screen.blit(surf, rect)


def _draw_ambient(screen, font, t: float) -> None:
    w, h = screen.get_size()
    base = int(20 + state.hue * 40)
    r = min(255, base + int(30 * math.sin(t * 0.8)))
    g = min(255, base + int(25 * math.sin(t * 0.6 + 1.2)))
    b = min(255, base + int(35 * math.sin(t * 0.7 + 2.4)))
    screen.fill((r, g, b))

    # Beat flash overlay from Sonic Pi cue events.
    dt = time.monotonic() - state.last_hit_at
    if dt < 0.15:
        alpha = int(255 * (1.0 - dt / 0.15))
        flash = pygame.Surface((w, h), pygame.SRCALPHA)
        flash.fill((255, 255, 255, alpha))
        screen.blit(flash, (0, 0))

    _draw_text_center(screen, "ambient mode", font, y_offset=0)


def _draw_phase_scene(screen, font) -> None:
    screen.fill((0, 0, 0))
    if state.phase == "talking":
        _draw_text_center(screen, "...talking to plant", font)
    elif state.phase == "listening":
        _draw_text_center(screen, "..listening to plant", font)
    elif state.phase == "thanks":
        _draw_text_center(screen, "thanks for listening", font)


async def _run_pygame_renderer() -> None:
    pygame.init()
    screen = pygame.display.set_mode((1000, 600))
    pygame.display.set_caption("Botanical Beats Visualizer")
    font = None
    try:
        pygame.font.init()
        font = pygame.font.SysFont("Helvetica", 48)
    except Exception as exc:
        print(f"[viz] pygame font unavailable, running without on-screen text: {exc}")
    clock = pygame.time.Clock()

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        if state.phase == "idle":
            _draw_ambient(screen, font, time.monotonic())
        else:
            _draw_phase_scene(screen, font)

        pygame.display.flip()
        clock.tick(60)
        await asyncio.sleep(0)

    pygame.quit()


async def _run_console_renderer() -> None:
    print("[viz] Not using pygame. Running console visualizer.")
    while True:
        if state.phase == "idle":
            print(
                f"[viz] ambient phase={state.phase} hue={state.hue:.2f} energy={state.energy:.2f}"
            )
        elif state.phase == "talking":
            print("[viz] ...talking to plant")
        elif state.phase == "listening":
            print("[viz] ..listening to plant")
        elif state.phase == "thanks":
            print("[viz] thanks for listening")
        await asyncio.sleep(1.0)


async def main() -> None:
    dispatcher = Dispatcher()
    dispatcher.map("/state/idle", _set_phase("idle"))
    dispatcher.map("/state/talking", _set_phase("talking"))
    dispatcher.map("/state/listening", _set_phase("listening"))
    dispatcher.map("/state/listenting", _set_phase("listening"))
    dispatcher.map("/state/thanks", _set_phase("thanks"))

    dispatcher.map("/viz/mod/hue", _mod_hue)
    dispatcher.map("/viz/mod/energy", _mod_energy)

    dispatcher.map("/cue/snare", _cue_snare)
    dispatcher.map("/cue/hit", _cue_hit)
    dispatcher.map("/cue/note", _cue_note)

    loop = asyncio.get_event_loop()
    server = AsyncIOOSCUDPServer(("127.0.0.1", 9001), dispatcher, loop)
    transport, _ = await server.create_serve_endpoint()
    try:
        if _HAS_PYGAME:
            try:
                await _run_pygame_renderer()
            except Exception as exc:
                print(f"[viz] Not using pygame due to runtime error: {exc}")
                await _run_console_renderer()
        else:
            await _run_console_renderer()
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
