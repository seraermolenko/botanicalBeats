import asyncio
import colorsys
import math
import random
import time
from dataclasses import dataclass, field

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
    fan: float = 0.5
    light: float = 0.5
    frozen_hue: float = 0.5
    audio_level: float = 0.0
    last_hit_at: float = 0.0
    hit_energy: float = 0.0
    note_energy: float = 0.0
    snare_energy: float = 0.0
    last_note_midi: float = 60.0
    burst_requests: list["BurstRequest"] = field(default_factory=list)


state = VizState()
_lava_blobs: list["LavaBlob"] = []
_fire_particles: list["FireParticle"] = []


@dataclass
class BurstRequest:
    intensity: float
    hue: float
    midi: float | None = None


@dataclass
class LavaBlob:
    x: float
    y: float
    vx: float
    vy: float
    radius: float
    hue: float
    alpha: int


@dataclass
class FireParticle:
    x: float
    y: float
    prev_x: float
    prev_y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: tuple[int, int, int]
    size: int


def _set_phase(phase: str):
    def handler(_address, *_args):
        state.phase = phase
        print(f"[viz] phase -> {phase}")

    return handler


def _mod_hue(_address, value):
    state.hue = float(value)


def _mod_energy(_address, value):
    state.energy = float(value)


def _frozen_fan(_address, value):
    state.fan = max(0.0, min(1.0, float(value)))


def _frozen_hue(_address, value):
    state.frozen_hue = max(0.0, min(1.0, float(value)))


def _frozen_light(_address, value):
    state.light = max(0.0, min(1.0, float(value)))


def _audio_pulse(_address, value):
    state.audio_level = max(state.audio_level, max(0.0, min(1.0, float(value))))


def _cue_snare(_address, beat, bar, vel):
    state.last_hit_at = time.monotonic()
    state.snare_energy = max(state.snare_energy, min(1.0, float(vel)))
    state.hit_energy = max(state.hit_energy, min(1.0, float(vel)))
    # Snare should always produce a visible burst for audiovisual sync.
    state.burst_requests.append(BurstRequest(intensity=float(vel), hue=state.hue))
    print(f"[viz] cue snare beat={beat} bar={bar} vel={vel}")


def _cue_hit(_address, name, beat, bar, vel):
    state.last_hit_at = time.monotonic()
    state.hit_energy = max(state.hit_energy, min(1.0, float(vel)))
    state.burst_requests.append(BurstRequest(intensity=max(0.62, float(vel)), hue=state.hue))
    print(f"[viz] cue hit name={name} beat={beat} bar={bar} vel={vel}")


def _cue_note(_address, midi, dur, beat, bar, vel):
    state.last_hit_at = time.monotonic()
    state.note_energy = max(state.note_energy, min(1.0, float(vel)))
    state.last_note_midi = float(midi)
    if state.phase == "listening":
        state.burst_requests.append(
            BurstRequest(intensity=float(vel), hue=(state.hue + 0.08) % 1.0, midi=float(midi))
        )
    print(f"[viz] cue note midi={midi} dur={dur} beat={beat} bar={bar} vel={vel}")


def _hsv_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(max(0.0, min(1.0, h)), max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return int(r * 255), int(g * 255), int(b * 255)


def _draw_text_center(screen, text: str, font, y_offset: int = 0) -> None:
    if font is None:
        return
    surf = font.render(text, True, (36, 44, 52))
    rect = surf.get_rect(center=(screen.get_width() // 2, screen.get_height() // 2 + y_offset))
    screen.blit(surf, rect)


def _draw_phase_label(screen, text: str, font) -> None:
    if font is None:
        return
    label_font = font
    surf = label_font.render(text, True, (20, 28, 36))
    pad_x, pad_y = 18, 10
    box_w = surf.get_width() + pad_x * 2
    box_h = surf.get_height() + pad_y * 2
    x = (screen.get_width() - box_w) // 2
    y = int(screen.get_height() * 0.08)

    badge = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    badge.fill((255, 255, 255, 220))
    screen.blit(badge, (x, y))
    screen.blit(surf, (x + pad_x, y + pad_y))


def _draw_ambient(screen, font, t: float) -> None:
    w, h = screen.get_size()
    base_hue = (state.frozen_hue * 0.7 + state.hue * 0.3) % 1.0
    r, g, b = _hsv_rgb(base_hue, 0.22, 0.95)
    screen.fill((r, g, b))

    dt = time.monotonic() - state.last_hit_at
    if dt < 0.1:
        alpha = int(55 * (1.0 - dt / 0.1))
        flash = pygame.Surface((w, h), pygame.SRCALPHA)
        flash.fill((255, 255, 255, alpha))
        screen.blit(flash, (0, 0))

    audio_alpha = int(85 * state.audio_level)
    if audio_alpha > 0:
        pulse = pygame.Surface((w, h), pygame.SRCALPHA)
        pulse.fill((255, 255, 255, audio_alpha))
        screen.blit(pulse, (0, 0))

    _draw_phase_label(screen, "IDLE", font)


def _draw_vertical_gradient(screen, top_color: tuple[int, int, int], bottom_color: tuple[int, int, int]) -> None:
    w, h = screen.get_size()
    for y in range(h):
        a = y / max(1, h - 1)
        r = int(top_color[0] * (1.0 - a) + bottom_color[0] * a)
        g = int(top_color[1] * (1.0 - a) + bottom_color[1] * a)
        b = int(top_color[2] * (1.0 - a) + bottom_color[2] * a)
        pygame.draw.line(screen, (r, g, b), (0, y), (w, y))


def _ensure_lava_blobs(w: int, h: int) -> None:
    if _lava_blobs:
        return
    count = random.randint(5, 8)
    min_r = int(h * 0.10)
    max_r = int(h * 0.20)
    for i in range(count):
        radius = random.uniform(min_r, max_r)
        _lava_blobs.append(
            LavaBlob(
                x=random.uniform(radius, w - radius),
                y=random.uniform(radius, h - radius),
                vx=random.uniform(-24.0, 24.0),
                vy=random.uniform(-20.0, 20.0),
                radius=radius,
                hue=(state.frozen_hue + i * 0.06 + random.uniform(-0.03, 0.03)) % 1.0,
                alpha=random.randint(42, 78),
            )
        )


def _spawn_firework(req: BurstRequest, w: int, h: int) -> None:
    intensity = max(0.15, min(1.0, req.intensity))
    x = random.uniform(w * 0.15, w * 0.85)
    if req.midi is not None:
        pitch_norm = max(0.0, min(1.0, (req.midi - 36.0) / 60.0))
        y = h * (0.78 - pitch_norm * 0.52)
    else:
        y = random.uniform(h * 0.22, h * 0.65)

    count = int(16 + intensity * 48)
    speed = 90.0 + intensity * 220.0
    base_hue = req.hue

    for _ in range(count):
        ang = random.uniform(0.0, math.tau)
        spd = speed * random.uniform(0.55, 1.05)
        vx = math.cos(ang) * spd
        vy = math.sin(ang) * spd - random.uniform(12.0, 60.0)
        life = random.uniform(0.45, 0.95)
        hue = (base_hue + random.uniform(-0.06, 0.06)) % 1.0
        sat = random.uniform(0.55, 0.9)
        val = random.uniform(0.25, 0.75)
        color = _hsv_rgb(hue, sat, val)
        _fire_particles.append(
            FireParticle(
                x=x,
                y=y,
                prev_x=x,
                prev_y=y,
                vx=vx,
                vy=vy,
                life=life,
                max_life=life,
                color=color,
                size=random.randint(1, 3),
            )
        )


def _update_draw_particles(screen, dt: float) -> None:
    gravity = 240.0
    canvas = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    keep: list[FireParticle] = []
    for p in _fire_particles:
        p.prev_x, p.prev_y = p.x, p.y
        p.vy += gravity * dt
        p.x += p.vx * dt
        p.y += p.vy * dt
        p.life -= dt
        if p.life <= 0.0:
            continue
        life_n = p.life / p.max_life
        alpha = int(255 * (life_n ** 1.6))
        sx, sy = int(p.x), int(p.y)
        tx, ty = int(p.prev_x), int(p.prev_y)
        pygame.draw.line(canvas, (*p.color, max(0, alpha // 2)), (tx, ty), (sx, sy), width=1)
        pygame.draw.circle(canvas, (*p.color, alpha), (sx, sy), p.size)
        keep.append(p)
    _fire_particles[:] = keep
    screen.blit(canvas, (0, 0))


def _draw_listening_scene(screen, font, t: float, dt: float) -> None:
    w, h = screen.get_size()
    _ensure_lava_blobs(w, h)

    state.hit_energy *= 0.93
    state.note_energy *= 0.94
    state.snare_energy *= 0.92

    base_hue = (state.frozen_hue * 0.75 + state.hue * 0.25) % 1.0
    top = _hsv_rgb(base_hue, 0.20, 0.98)
    bottom = _hsv_rgb((base_hue + 0.03) % 1.0, 0.22, 0.90)
    _draw_vertical_gradient(screen, top, bottom)

    blobs_layer = pygame.Surface((w, h), pygame.SRCALPHA)
    music_energy = max(state.hit_energy, state.note_energy, state.snare_energy, state.energy, state.audio_level)
    speed_mul = 0.35 + state.fan * 2.6
    flicker_mul = 0.15 + state.light * 0.85
    vibe_freq = 0.7 + state.frozen_hue * 3.2
    vibe_amp = 0.8 + state.frozen_hue * 6.5
    for i, blob in enumerate(_lava_blobs):
        vibex = math.sin(t * (vibe_freq + i * 0.05) + i * 0.9) * vibe_amp
        vibey = math.cos(t * (vibe_freq * 0.8 + i * 0.07) + i * 0.4) * vibe_amp
        blob.x += blob.vx * dt * speed_mul + vibex * dt
        blob.y += blob.vy * dt * speed_mul + vibey * dt

        if blob.x - blob.radius <= 0:
            blob.x = blob.radius
            blob.vx = abs(blob.vx)
        elif blob.x + blob.radius >= w:
            blob.x = w - blob.radius
            blob.vx = -abs(blob.vx)
        if blob.y - blob.radius <= 0:
            blob.y = blob.radius
            blob.vy = abs(blob.vy)
        elif blob.y + blob.radius >= h:
            blob.y = h - blob.radius
            blob.vy = -abs(blob.vy)

        blob.hue = (blob.hue + 0.005 * dt + 0.0004 * math.sin(t * 0.5 + i)) % 1.0
        flicker = (0.5 + 0.5 * math.sin(t * (2.2 + i * 0.13) + i)) * flicker_mul
        value = 0.48 + 0.30 * max(0.0, min(1.0, state.energy)) + 0.22 * music_energy + 0.16 * flicker
        value = max(0.0, min(1.0, value))
        color = _hsv_rgb(blob.hue, 0.45, value)
        alpha = int(min(210, blob.alpha + music_energy * 90 + state.light * 35))
        pygame.draw.circle(blobs_layer, (*color, alpha), (int(blob.x), int(blob.y)), int(blob.radius))
    screen.blit(blobs_layer, (0, 0))

    # Flower-like bloom overlay: rotating translucent petals that open with sound energy.
    petals = pygame.Surface((w, h), pygame.SRCALPHA)
    cx, cy = w // 2, h // 2
    petal_count = 12
    bloom = 0.35 + music_energy * 0.95
    ring_r = min(w, h) * (0.14 + 0.06 * bloom)
    petal_w = int(min(w, h) * (0.07 + 0.04 * bloom))
    petal_h = int(min(w, h) * (0.20 + 0.10 * bloom))
    for i in range(petal_count):
        ang = (math.tau * i / petal_count) + t * (0.18 + 0.25 * state.fan)
        px = cx + math.cos(ang) * ring_r
        py = cy + math.sin(ang) * ring_r
        ph = (base_hue + i * 0.018 + 0.03 * math.sin(t + i)) % 1.0
        pr, pg, pb = _hsv_rgb(ph, 0.42, 0.78 + 0.18 * music_energy)
        alpha = int(38 + 110 * bloom)
        pygame.draw.ellipse(
            petals,
            (pr, pg, pb, alpha),
            (int(px - petal_w * 0.5), int(py - petal_h * 0.5), petal_w, petal_h),
        )
        # Blossom center glow.
        pygame.draw.circle(
            petals,
            (255, 255, 255, int(10 + 45 * music_energy)),
            (cx, cy),
            int(min(w, h) * (0.08 + 0.03 * bloom)),
        )
    screen.blit(petals, (0, 0))

    _draw_phase_label(screen, "LISTENING", font)


def _draw_phase_scene(screen, font) -> None:
    base_hue = (state.frozen_hue * 0.7 + state.hue * 0.3) % 1.0
    r, g, b = _hsv_rgb(base_hue, 0.15, 0.95)
    screen.fill((r, g, b))
    if state.phase == "talking":
        _draw_phase_label(screen, "TALKING", font)
    elif state.phase == "thanks":
        _draw_phase_label(screen, "THANK YOU", font)

    # Subtle audio-reactive overlay for non-listening phases.
    if state.audio_level > 0.01:
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        alpha = int(70 * state.audio_level)
        overlay.fill((255, 255, 255, alpha))
        screen.blit(overlay, (0, 0))


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

        dt = max(0.0001, clock.get_time() / 1000.0)
        if state.phase == "idle":
            _draw_ambient(screen, font, time.monotonic())
        else:
            if state.phase == "listening":
                _draw_listening_scene(screen, font, time.monotonic(), dt)
            else:
                _draw_phase_scene(screen, font)

        # Draw cue bursts over every phase so touch/hit always has visual feedback.
        while state.burst_requests:
            _spawn_firework(state.burst_requests.pop(0), screen.get_width(), screen.get_height())
        _update_draw_particles(screen, dt)
        state.audio_level *= 0.9

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
    dispatcher.map("/viz/audio/pulse", _audio_pulse)
    dispatcher.map("/frozen/fan", _frozen_fan)
    dispatcher.map("/frozen/hue", _frozen_hue)
    dispatcher.map("/frozen/light", _frozen_light)

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
