import asyncio
import colorsys
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
    hit_energy: float = 0.0
    note_energy: float = 0.0
    snare_energy: float = 0.0
    last_note_midi: float = 60.0


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
    state.snare_energy = max(state.snare_energy, min(1.0, float(vel)))
    state.hit_energy = max(state.hit_energy, min(1.0, float(vel)))
    print(f"[viz] cue snare beat={beat} bar={bar} vel={vel}")


def _cue_hit(_address, name, beat, bar, vel):
    state.last_hit_at = time.monotonic()
    state.hit_energy = max(state.hit_energy, min(1.0, float(vel)))
    print(f"[viz] cue hit name={name} beat={beat} bar={bar} vel={vel}")


def _cue_note(_address, midi, dur, beat, bar, vel):
    state.last_hit_at = time.monotonic()
    state.note_energy = max(state.note_energy, min(1.0, float(vel)))
    state.last_note_midi = float(midi)
    print(f"[viz] cue note midi={midi} dur={dur} beat={beat} bar={bar} vel={vel}")


def _hsv_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(max(0.0, min(1.0, h)), max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return int(r * 255), int(g * 255), int(b * 255)


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


def _draw_vertical_gradient(screen, top_color: tuple[int, int, int], bottom_color: tuple[int, int, int]) -> None:
    w, h = screen.get_size()
    for y in range(h):
        a = y / max(1, h - 1)
        r = int(top_color[0] * (1.0 - a) + bottom_color[0] * a)
        g = int(top_color[1] * (1.0 - a) + bottom_color[1] * a)
        b = int(top_color[2] * (1.0 - a) + bottom_color[2] * a)
        pygame.draw.line(screen, (r, g, b), (0, y), (w, y))


def _draw_listening_orb(screen, font, t: float) -> None:
    w, h = screen.get_size()
    cx, cy = w // 2, h // 2
    min_dim = min(w, h)

    state.hit_energy *= 0.92
    state.note_energy *= 0.95
    state.snare_energy *= 0.90

    base_energy = max(0.0, min(1.0, state.energy))
    reactive = max(state.hit_energy, state.note_energy, state.snare_energy)
    pulse = base_energy * 0.6 + reactive * 0.8

    top = _hsv_rgb((state.hue + 0.08) % 1.0, 0.55, 0.16 + 0.18 * pulse)
    bottom = _hsv_rgb((state.hue + 0.62) % 1.0, 0.75, 0.10 + 0.20 * pulse)
    _draw_vertical_gradient(screen, top, bottom)

    # Soft drifting nebula in the background.
    nebula = pygame.Surface((w, h), pygame.SRCALPHA)
    for i in range(6):
        ang = t * (0.08 + i * 0.013) + i * 1.3
        nx = int(cx + math.cos(ang) * (min_dim * (0.18 + i * 0.05)))
        ny = int(cy + math.sin(ang * 1.2) * (min_dim * (0.10 + i * 0.04)))
        radius = int(min_dim * (0.18 + i * 0.02))
        color = _hsv_rgb((state.hue + i * 0.11) % 1.0, 0.65, 0.45)
        alpha = 20 + i * 8
        pygame.draw.circle(nebula, (*color, alpha), (nx, ny), radius)
    screen.blit(nebula, (0, 0))

    orb_radius = int(min_dim * (0.16 + 0.07 * pulse + 0.015 * math.sin(t * 2.4)))
    ring_wobble = 8 + 22 * pulse

    # Orb halo and shell.
    halo = pygame.Surface((w, h), pygame.SRCALPHA)
    for i in range(5):
        r = orb_radius + (i + 1) * 22
        alpha = max(0, int(70 - i * 12 + pulse * 40))
        color = _hsv_rgb((state.hue + 0.03 * i) % 1.0, 0.8, 0.9)
        pygame.draw.circle(halo, (*color, alpha), (cx, cy), r, width=max(2, 6 - i))
    screen.blit(halo, (0, 0))

    orb = pygame.Surface((w, h), pygame.SRCALPHA)
    core_color = _hsv_rgb((state.hue + 0.02) % 1.0, 0.55, 0.98)
    edge_color = _hsv_rgb((state.hue + 0.42) % 1.0, 0.88, 0.65)
    pygame.draw.circle(orb, (*edge_color, 220), (cx, cy), orb_radius)
    pygame.draw.circle(orb, (*core_color, 240), (cx, cy), int(orb_radius * 0.72))
    pygame.draw.circle(orb, (255, 255, 255, 70), (cx - orb_radius // 4, cy - orb_radius // 4), int(orb_radius * 0.32))
    screen.blit(orb, (0, 0))

    # Audio-reactive orbital rings.
    rings = pygame.Surface((w, h), pygame.SRCALPHA)
    note_bend = (state.last_note_midi - 60.0) / 24.0
    for i in range(3):
        rr = orb_radius + 36 + i * 28 + int(math.sin(t * (1.3 + i * 0.2) + i) * ring_wobble)
        rx = rr + int(note_bend * 18)
        ry = rr - int(note_bend * 10)
        color = _hsv_rgb((state.hue + 0.15 * i + 0.2 * pulse) % 1.0, 0.75, 0.9)
        alpha = int(80 + reactive * 110 - i * 18)
        pygame.draw.ellipse(
            rings,
            (*color, max(20, alpha)),
            (cx - rx, cy - ry, rx * 2, ry * 2),
            width=2 + i,
        )
    screen.blit(rings, (0, 0))

    # Star sparks for hit/note moments.
    sparks = pygame.Surface((w, h), pygame.SRCALPHA)
    spark_count = 10 + int(30 * reactive)
    for i in range(spark_count):
        ang = (i / max(1, spark_count)) * math.tau + t * 0.7
        dist = orb_radius + 24 + (i % 5) * 14 + int(18 * math.sin(t * 2.5 + i))
        sx = int(cx + math.cos(ang) * dist)
        sy = int(cy + math.sin(ang * 1.1) * dist)
        c = _hsv_rgb((state.hue + i * 0.03) % 1.0, 0.55, 1.0)
        a = 90 + int(120 * reactive)
        pygame.draw.circle(sparks, (*c, min(255, a)), (sx, sy), 2 + (i % 2))
    screen.blit(sparks, (0, 0))

    _draw_text_center(screen, "..listening to plant", font, y_offset=int(min_dim * 0.28))


def _draw_phase_scene(screen, font) -> None:
    screen.fill((7, 8, 10))
    if state.phase == "talking":
        _draw_text_center(screen, "...talking to plant", font)
    elif state.phase == "listening":
        _draw_listening_orb(screen, font, time.monotonic())
    elif state.phase == "thanks":
        _draw_text_center(screen, "thanks for listening", font)


async def _run_pygame_renderer() -> None:
    pygame.init()
    screen = pygame.display.set_mode((1000, 600))
    pygame.display.set_caption("Botanical Beats Visualizer")
    font = None
    try:
        pygame.font.init()
        font = pygame.font.SysFont("Avenir Next", 46)
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
