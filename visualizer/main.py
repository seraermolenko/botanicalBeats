"""
Pygame-based visualizer — merged from display.py (rich visuals) + original (full OSC handling).

Three visual modes:
  IDLE:       Dreamy particle field — glowing dots drift and pulse,
              color driven by frozen_hue, size/brightness react to audio amplitude.
              Particle speed driven by frozen_fan.
  TALKING:    Pulsing green orb — we are talking TO the plant, it listens.
              Calm, receptive energy.
  LISTENING:  Pixelated plant character bops and dances in sync with music —
              the plant is talking back. Beat hits trigger bounce/squish/wiggle.

Special states:
  THANKS:     Warm flash + "THANK YOU!" + mood-engine plant emotion sentence.
              Auto-transitions back to idle after 10s.
  (fallback): Phase name displayed centered on hue-tinted background.

OSC addresses handled:
  /state/idle        → IDLE
  /state/talking     → TALKING  (we speak to the plant → orb)
  /state/listening   → LISTENING (plant speaks back → dancing pixel plant)
  /state/listenting  → LISTENTING (radial audio analyzer)
  /state/thanks      → THANKS → idle

  /viz/mod/hue       → float 0-1, LED hue accent
  /viz/mod/energy    → float 0-1, general energy
  /viz/audio/pulse   → float 0-1, audio amplitude
  /frozen/hue        → float 0-1, ambient hue bias (primary particle color)
  /frozen/light      → float 0-1, brightness bias
  /frozen/fan        → float 0-1, particle motion speed bias

  /cue/snare         → (beat, bar, vel)
  /cue/hit           → (name, beat, bar, vel)
  /cue/note          → (midi, dur, beat, bar, vel)
  /cue/bar           → bar flash
"""

import asyncio
import colorsys
import math
import random
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

# ─── Configuration ────────────────────────────────────────────────────────────

OSC_HOST = "127.0.0.1"
OSC_PORT = 9001
WIDTH = 900
HEIGHT = 520
FPS = 60
PARTICLE_COUNT = 72

# Pixel plant sprite — 16×24 grid, each cell is PIXEL_SZ px square.
# 0=transparent, 1=leaf, 2=stem, 3=soil/pot, 4=highlight, 5=dark leaf, 6=flower/tip
PIXEL_SZ = 14  # base pixel block size

# Plant sprite map (16 wide × 24 tall)
# Rows read top→bottom
PLANT_SPRITE = [
    "0000000110000000",
    "0000011111100000",
    "0000111111110000",
    "0001111441111000",
    "0001114441111000",
    "0000115511100000",
    "0001155511110000",
    "0001115551110000",
    "0000011551100000",
    "0000001551000000",
    "0000001221000000",
    "0000112221100000",
    "0001122222110000",
    "0001122222110000",
    "0001122222110000",
    "0000122221100000",
    "0000012221000000",
    "0333333333333300",
    "0333333333333300",
    "0033344433300000",  # pot
    "0003333333000000",
    "0003333333000000",
    "0000033330000000",
    "0000000000000000",
]

# ─── Shared OSC-driven state ──────────────────────────────────────────────────

@dataclass
class VizState:
    phase: str = "idle"
    hue: float = 0.5
    energy: float = 0.0
    audio_level: float = 0.0
    frozen_hue: float = 0.5
    frozen_light: float = 0.5
    frozen_fan: float = 0.5
    last_hit_at: float = 0.0
    hit_energy: float = 0.0
    note_energy: float = 0.0
    snare_energy: float = 0.0
    flash_until: float = 0.0
    bar_flash_until: float = 0.0
    # Plant bounce/squish state
    plant_bounce: float = 0.0   # 0-1, decays each frame
    plant_squish: float = 0.0   # 0-1, independent squish axis
    plant_wiggle: float = 0.0   # lateral sway accumulator
    # Thanks/emotion state
    plant_emotion: str = ""
    # Running session stats
    total_hits: int = 0
    total_notes: int = 0
    total_bars: int = 0
    peak_amplitude: float = 0.0


state = VizState()


# ─── OSC handlers ─────────────────────────────────────────────────────────────

def _set_phase(phase: str):
    def handler(_address, *_args):
        state.phase = phase
        print(f"[viz] phase -> {phase}")
    return handler


def _mod_hue(_address, value):
    state.hue = float(value) % 1.0


def _mod_energy(_address, value):
    state.energy = max(0.0, min(1.0, float(value)))


def _audio_pulse(_address, value):
    state.audio_level = max(state.audio_level, max(0.0, min(1.0, float(value))))


def _frozen_hue(_address, value):
    state.frozen_hue = max(0.0, min(1.0, float(value)))


def _frozen_light(_address, value):
    state.frozen_light = max(0.0, min(1.0, float(value)))


def _frozen_fan(_address, value):
    state.frozen_fan = max(0.0, min(1.0, float(value)))


def _cue_snare(_address, beat, bar, vel):
    state.last_hit_at = time.monotonic()
    state.snare_energy = max(state.snare_energy, min(1.0, float(vel)))
    state.hit_energy = max(state.hit_energy, min(1.0, float(vel)))
    state.flash_until = time.monotonic() + 0.12
    state.plant_bounce = min(1.0, state.plant_bounce + float(vel) * 1.0)
    state.plant_squish = min(1.0, state.plant_squish + float(vel) * 0.6)
    state.total_hits += 1


def _cue_hit(_address, name, beat, bar, vel):
    state.last_hit_at = time.monotonic()
    state.hit_energy = max(state.hit_energy, min(1.0, float(vel)))
    state.flash_until = time.monotonic() + 0.12
    state.audio_level = max(state.audio_level, 0.9)
    state.plant_bounce = min(1.0, state.plant_bounce + float(vel) * 0.8)
    state.total_hits += 1


def _cue_note(_address, midi, dur, beat, bar, vel):
    state.last_hit_at = time.monotonic()
    state.note_energy = max(state.note_energy, min(1.0, float(vel)))
    state.plant_wiggle += float(vel) * 0.4
    state.total_notes += 1


def _cue_bar(_address, *_args):
    state.bar_flash_until = time.monotonic() + 0.18
    state.plant_bounce = 1.0
    state.total_bars += 1


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _hsv_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(
        max(0.0, min(1.0, h)),
        max(0.0, min(1.0, s)),
        max(0.0, min(1.0, v)),
    )
    return int(r * 255), int(g * 255), int(b * 255)


def _draw_phase_label(screen, text: str, font, surfs, t: float = 0.0) -> None:
    """Friendly animated badge showing the current state."""
    if font is None:
        return
    # Animate trailing dots on any text ending with "..."
    if text.endswith("..."):
        dots = "." * (int(t * 2) % 4)
        text = text[:-3] + dots
    surf = font.render(text, True, (20, 28, 36))
    pad_x, pad_y = 14, 8
    box_w = surf.get_width() + pad_x * 2
    box_h = surf.get_height() + pad_y * 2
    x = (screen.get_width() - box_w) // 2
    y = int(screen.get_height() * 0.05)
    # Reuse badge surface if size matches, otherwise reallocate (rare — only on font change)
    if surfs.badge is None or surfs.badge.get_size() != (box_w, box_h):
        surfs.badge = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    surfs.badge.fill((255, 255, 255, 180))
    screen.blit(surfs.badge, (x, y))
    screen.blit(surf, (x + pad_x, y + pad_y))


def _wrap_text(font, text: str, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.size(candidate)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


# ─── IDLE: Dreamy glowing particle field ──────────────────────────────────────

def _make_particles() -> list[dict]:
    return [
        {
            "x": random.uniform(0, WIDTH),
            "y": random.uniform(0, HEIGHT),
            "vx": random.uniform(-0.35, 0.35),
            "vy": random.uniform(-0.35, 0.35),
            "base_size": random.uniform(2.5, 6.5),
            "phase": random.uniform(0, math.tau),
            "hue_offset": random.uniform(-0.08, 0.08),
        }
        for _ in range(PARTICLE_COUNT)
    ]


_particles = _make_particles()


def _draw_idle(screen, font, surfs, t: float, amplitude: float, hue: float, brightness: float) -> None:
    surfs.fade.fill((5, 5, 18))
    surfs.fade.set_alpha(28)
    screen.blit(surfs.fade, (0, 0))

    if time.monotonic() < state.flash_until:
        remaining = state.flash_until - time.monotonic()
        surfs.flash.fill((255, 255, 255, int(40 * (remaining / 0.12))))
        screen.blit(surfs.flash, (0, 0))

    if time.monotonic() < state.bar_flash_until:
        surfs.bar_flash.fill((255, 240, 180, 55))
        screen.blit(surfs.bar_flash, (0, 0))

    surfs.particle_layer.fill((0, 0, 0, 0))
    particle_layer = surfs.particle_layer
    speed_bias = 0.5 + state.frozen_fan * 1.5

    for p in _particles:
        p["x"] += (p["vx"] + math.sin(t * 0.9 + p["phase"]) * 0.22) * speed_bias
        p["y"] += (p["vy"] + math.cos(t * 0.65 + p["phase"]) * 0.22) * speed_bias
        p["x"] %= WIDTH
        p["y"] %= HEIGHT

        pulse = 1.0 + amplitude * 3.5 + state.hit_energy * 2.0
        size = max(1, int(p["base_size"] * pulse))

        ph = (hue + p["hue_offset"]) % 1.0
        val = min(1.0, brightness * 0.55 + 0.28 + amplitude * 0.45)
        r, g, b = _hsv_rgb(ph, 0.65, val)

        glow_alpha = int(30 + amplitude * 60)
        pygame.draw.circle(particle_layer, (r, g, b, glow_alpha), (int(p["x"]), int(p["y"])), size * 2)

        core_alpha = int(140 + amplitude * 100)
        pygame.draw.circle(particle_layer, (r, g, b, core_alpha), (int(p["x"]), int(p["y"])), size)

    screen.blit(particle_layer, (0, 0))
    _draw_phase_label(screen, "waiting for the plant...", font, surfs, t)


# ─── LISTENING: Pulsing green orb + ripples + animated dots ──────────────────

def _draw_listening(screen, font, surfs, t: float) -> None:
    # Light background — soft warm white tinted by hue
    amplitude = max(state.audio_level, state.hit_energy * 0.7, state.energy * 0.5)
    hue = (state.frozen_hue * 0.65 + state.hue * 0.35) % 1.0
    bg_r, bg_g, bg_b = _hsv_rgb(hue, 0.07, 0.97)
    screen.fill((bg_r, bg_g, bg_b))

    cx, cy = WIDTH // 2, HEIGHT // 2

    # ── Layer 1: slow rotating background rings ───────────────────────────────
    surfs.ripple.fill((0, 0, 0, 0))
    num_bg_rings = 6
    for i in range(num_bg_rings):
        ring_hue = (hue + i * 0.06) % 1.0
        r, g, b = _hsv_rgb(ring_hue, 0.55, 0.55 + i * 0.04)  # darker rings on light bg
        base_radius = 60 + i * 38
        wobble = math.sin(t * 0.7 + i * 1.1) * 6
        pygame.draw.circle(surfs.ripple, (r, g, b, 55), (cx, cy),
                           max(4, int(base_radius + wobble)), 1)
    screen.blit(surfs.ripple, (0, 0))

    # ── Layer 2: radial spikes — the main burst ───────────────────────────────
    surfs.orbit_layer.fill((0, 0, 0, 0))
    NUM_SPIKES = 64
    for i in range(NUM_SPIKES):
        angle = (i / NUM_SPIKES) * math.tau

        # Each spike has its own phase so they ripple around the circle
        spike_phase = t * 2.8 + i * (math.tau / NUM_SPIKES) * 2.5
        note_spike  = state.note_energy * 0.6 * math.sin(t * 6.0 + i * 0.4)
        snare_spike = state.snare_energy * math.exp(-((i - NUM_SPIKES // 4) ** 2) / 80.0)

        length = (
            28                                          # base
            + amplitude * 110                          # amplitude stretches all spikes
            + 30 * math.sin(spike_phase)               # rolling wave
            + note_spike * 55                          # notes add pointy bursts
            + snare_spike * 70                         # snare hits one quadrant hard
        )
        length = max(4, length)

        inner_r = 28 + amplitude * 18
        ox = cx + math.cos(angle) * inner_r
        oy = cy + math.sin(angle) * inner_r
        ex = cx + math.cos(angle) * (inner_r + length)
        ey = cy + math.sin(angle) * (inner_r + length)

        # Hue rotates around the ring + shifts with OSC hue
        spike_hue = (hue + i / NUM_SPIKES * 0.5 + t * 0.04) % 1.0
        brightness = min(0.75, 0.35 + amplitude * 0.35 + state.snare_energy * 0.2)  # darker for light bg
        r, g, b = _hsv_rgb(spike_hue, 0.90, brightness)

        # Thick inner glow line + thin bright outer tip
        alpha_outer = int(180 + amplitude * 75)
        alpha_inner = int(80 + amplitude * 60)
        tip_len = length * 0.35
        mid_x = cx + math.cos(angle) * (inner_r + length - tip_len)
        mid_y = cy + math.sin(angle) * (inner_r + length - tip_len)

        pygame.draw.line(surfs.orbit_layer, (r, g, b, alpha_inner),
                         (int(ox), int(oy)), (int(mid_x), int(mid_y)), 3)
        pygame.draw.line(surfs.orbit_layer, (r, g, b, alpha_outer),
                         (int(mid_x), int(mid_y)), (int(ex), int(ey)), 2)

    screen.blit(surfs.orbit_layer, (0, 0))

    # ── Layer 3: beat shockwave rings — expand outward on snare/hit ──────────
    surfs.glow_layer.fill((0, 0, 0, 0))
    # Use flash_until timing to drive ring expansion
    flash_age = max(0.0, t - (state.flash_until - 0.12 - (t - t)))  # approximate age
    now = time.monotonic()
    if state.flash_until > now:
        flash_progress = 1.0 - (state.flash_until - now) / 0.12
    else:
        flash_progress = 1.0
    for ring_i in range(3):
        offset = ring_i * 0.3
        expand = (flash_progress + offset) % 1.0
        ring_r = int(30 + expand * 220)
        ring_alpha = max(0, int(120 * (1.0 - expand)))
        sh, ss, sv = hue, 0.6, 0.95
        sr, sg, sb = _hsv_rgb(sh, ss, sv)
        if ring_alpha > 4:
            pygame.draw.circle(surfs.glow_layer, (sr, sg, sb, ring_alpha),
                               (cx, cy), ring_r, 2)
    screen.blit(surfs.glow_layer, (0, 0))

    # ── Layer 4: central orb ─────────────────────────────────────────────────
    orb_pulse = 0.5 + 0.5 * math.sin(t * 3.8)
    orb_radius = int(22 + amplitude * 28 + orb_pulse * 8 + state.snare_energy * 14)
    orb_r, orb_g, orb_b = _hsv_rgb(hue, 0.75, 0.55)  # richer, darker orb on light bg

    # Soft glow layers around orb
    surfs.highlight.fill((0, 0, 0, 0))
    for glow_i in range(5):
        gr = orb_radius + glow_i * 12
        ga = max(0, int(70 - glow_i * 14))
        pygame.draw.circle(surfs.highlight, (orb_r, orb_g, orb_b, ga), (cx, cy), gr)
    screen.blit(surfs.highlight, (0, 0))
    pygame.draw.circle(screen, (orb_r, orb_g, orb_b), (cx, cy), orb_radius)

    # Inner highlight
    hl_col = (min(255, orb_r + 60), min(255, orb_g + 60), min(255, orb_b + 60))
    pygame.draw.circle(screen, hl_col, (cx - orb_radius // 4, cy - orb_radius // 4),
                       max(3, orb_radius // 3))

    _draw_phase_label(screen, "plant is listening...", font, surfs, t)


# ─── TALKING: Pixelated plant character dancing to the music ─────────────────

def _build_plant_palette(hue: float, amplitude: float, t: float) -> dict:
    """
    Builds a color palette for the pixel plant.
    Hue shifts with OSC hue, amplitude brightens.
    Returns dict mapping sprite code → RGBA tuple.
    """
    leaf_h = (hue + 0.33) % 1.0          # green-ish leaves offset from accent hue
    dark_h = (hue + 0.35) % 1.0
    tip_h  = (hue + 0.05) % 1.0          # flower/tip close to accent hue
    stem_h = (hue + 0.30) % 1.0

    leaf_v  = min(0.65, 0.38 + amplitude * 0.27)   # richer, darker green
    dark_v  = min(0.45, 0.18 + amplitude * 0.22)   # deep shadow leaf
    tip_v   = min(0.75, 0.55 + amplitude * 0.20)   # vivid tip/flower
    stem_v  = min(0.55, 0.28 + amplitude * 0.22)   # darker stem
    pot_v   = min(0.60, 0.38 + amplitude * 0.18)   # terracotta-ish pot
    soil_v  = min(0.40, 0.22 + amplitude * 0.12)   # dark soil

    # Slight color shimmer on highlight with time
    hl_pulse = 0.5 + 0.5 * math.sin(t * 6.0)

    return {
        "0": None,  # transparent
        "1": (*_hsv_rgb(leaf_h, 0.70, leaf_v), 255),
        "2": (*_hsv_rgb(stem_h, 0.60, stem_v), 255),
        "3": (*_hsv_rgb(stem_h, 0.45, pot_v),  255),
        "4": (*_hsv_rgb(leaf_h, 0.25, min(1.0, leaf_v + 0.35 + hl_pulse * 0.1)), 255),  # highlight
        "5": (*_hsv_rgb(dark_h, 0.80, dark_v), 255),
        "6": (*_hsv_rgb(tip_h,  0.85, tip_v),  255),
    }


def _draw_plant_sprite(
    surface,
    cx: int,
    cy: int,
    pixel_sz: int,
    palette: dict,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    wiggle: float = 0.0,
    hue: float = 0.5,
    amplitude: float = 0.0,
    t: float = 0.0,
) -> None:
    """
    Renders the pixel-art plant sprite onto `surface`, centered at (cx, cy).
    scale_x / scale_y allow squish/stretch. wiggle shifts columns sideways.
    """
    rows = len(PLANT_SPRITE)
    cols = len(PLANT_SPRITE[0])

    total_w = int(cols * pixel_sz * scale_x)
    total_h = int(rows * pixel_sz * scale_y)
    origin_x = cx - total_w // 2
    origin_y = cy - total_h // 2

    for row_idx, row in enumerate(PLANT_SPRITE):
        for col_idx, code in enumerate(row):
            color = palette.get(code)
            if color is None:
                continue

            # Per-column lateral wiggle (top of plant sways more than base)
            row_fraction = row_idx / max(1, rows - 1)
            sway_amount = wiggle * (1.0 - row_fraction) * pixel_sz * 0.6

            bx = int(origin_x + col_idx * pixel_sz * scale_x + sway_amount)
            by = int(origin_y + row_idx * pixel_sz * scale_y)
            bw = max(1, int(pixel_sz * scale_x))
            bh = max(1, int(pixel_sz * scale_y))

            # Draw block
            pygame.draw.rect(surface, color[:3], (bx, by, bw, bh))

            # Subtle scanline pixel grid (dark border) for pixel-art feel
            if pixel_sz >= 6:
                border_col = (
                    max(0, color[0] - 40),
                    max(0, color[1] - 40),
                    max(0, color[2] - 40),
                )
                pygame.draw.rect(surface, border_col, (bx, by, bw, bh), 1)


def _draw_talking(screen, font, surfs, t: float, amplitude: float, hue: float) -> None:
    # Light background for the listening orb.
    bg_r, bg_g, bg_b = _hsv_rgb(hue, 0.07, 0.97)
    screen.fill((bg_r, bg_g, bg_b))

    cx, cy = WIDTH // 2, HEIGHT // 2

    # ── Slow outer ripple rings ───────────────────────────────────────────────
    surfs.ripple.fill((0, 0, 0, 0))
    for i in range(3):
        ripple_phase = t * 1.4 - i * 0.7
        ripple_r = int(90 + i * 28 + 18 * math.sin(ripple_phase))
        ripple_alpha = max(0, int(55 - i * 16))
        orb_r, orb_g, orb_b = _hsv_rgb(hue, 0.50, 0.52)
        pygame.draw.circle(surfs.ripple, (orb_r, orb_g, orb_b, ripple_alpha),
                           (cx, cy), ripple_r, 2)
    screen.blit(surfs.ripple, (0, 0))

    # ── Central pulsing orb ───────────────────────────────────────────────────
    pulse = 0.5 + 0.5 * math.sin(t * 3.1)
    radius = int(44 + pulse * 28)
    orb_r, orb_g, orb_b = _hsv_rgb(hue, 0.65, 0.45 + pulse * 0.22)
    pygame.draw.circle(screen, (orb_r, orb_g, orb_b), (cx, cy), radius)

    # Inner highlight
    surfs.highlight.fill((0, 0, 0, 0))
    hl_r = max(4, int(radius * 0.38))
    pygame.draw.circle(surfs.highlight, (255, 255, 255, int(55 + pulse * 45)),
                       (cx - radius // 5, cy - radius // 5), hl_r)
    screen.blit(surfs.highlight, (0, 0))

    _draw_phase_label(screen, "talking to plant...", font, surfs, t)


# ─── THANKS: Mood-engine plant emotion ───────────────────────────────────────

MOOD_LINES = {
    "OVERWHELMED": [
        "Ahh, this wind is intense. My leaves are drying out.",
        "Too bright. I am overwhelmed, can we soften the light?",
        "Wind is way too strong. I would love calmer air.",
        "Bright light plus big breeze is stress mode for me.",
        "Gentler please. I grow best with calm air and soft light.",
        "I am getting blasted, dim the light or lower the fan.",
    ],
    "HUNGRY": [
        "I am hungry for light. Please brighten it a bit.",
        "I can survive low light, but I cannot really grow here.",
        "More glow please. It is too dim to thrive.",
        "The breeze is fine, I just need more light.",
        "Feed me photons. A little brighter would help.",
        "I am stretching for light and feeling sleepy.",
    ],
    "CONTENT": [
        "This feels just right. Soft light and calm air, thank you.",
        "Comfy mode. Gentle glow and a calm breeze.",
        "I am chilling. My leaves feel relaxed and happy.",
        "Perfect balance. I can breathe and grow steadily.",
        "This is my sweet spot. Keep it here.",
        "Everything feels easy right now.",
    ],
    "INSPIRED": [
        "Yes, this light makes me feel like growing.",
        "Inspired. Bright enough for energy, gentle air to stay cool.",
        "I am in my growth era. Keep this steady.",
        "This is motivating, like sunny shade.",
        "I feel charged and ready to unfurl new leaves.",
        "Bright and kind. I am thriving.",
    ],
    "ALERT": [
        "Okay, I am awake now. Just do not push it too far.",
        "I feel active. Slightly less wind would be even nicer.",
        "Bright and breezy is fun, keep it gentle.",
        "I am alert and moving with the room.",
        "This is lively. A softer edge would be perfect.",
        "I can handle this, just not much more.",
    ],
}

HUE_LINES = {
    "red/pink": "Pink-red glow feels bold, just keep it soft.",
    "yellow": "Warm yellow light feels sunny, but not too intense.",
    "green": "Green vibes feel fresh and leafy.",
    "cyan": "Cyan feels crisp and airy.",
    "blue": "Blue light feels cool and focused.",
    "purple": "Purple glow feels dreamy and calm.",
}


def _bucket_light(light: float) -> str:
    if light < 0.25:
        return "low"
    if light < 0.60:
        return "ok"
    if light < 0.85:
        return "high"
    return "harsh"


def _bucket_wind(wind: float) -> str:
    if wind < 0.15:
        return "still"
    if wind < 0.40:
        return "calm"
    if wind < 0.65:
        return "breezy"
    return "strong"


def _hue_family(hue: float) -> str:
    deg = (hue % 1.0) * 360.0
    if deg >= 330.0 or deg < 30.0:
        return "red/pink"
    if deg < 70.0:
        return "yellow"
    if deg < 160.0:
        return "green"
    if deg < 200.0:
        return "cyan"
    if deg < 260.0:
        return "blue"
    return "purple"


def _choose_mood(light_bucket: str, wind_bucket: str) -> str:
    if light_bucket == "harsh" or wind_bucket == "strong":
        return "OVERWHELMED"
    if light_bucket == "low":
        return "HUNGRY"
    if light_bucket == "ok" and wind_bucket in ("still", "calm"):
        return "CONTENT"
    if light_bucket == "high" and wind_bucket in ("calm", "breezy"):
        return "INSPIRED"
    return "ALERT"


def _build_mood_message(light: float, wind: float, hue: float) -> str:
    light_bucket = _bucket_light(light)
    wind_bucket = _bucket_wind(wind)
    hue_bucket = _hue_family(hue)
    mood = _choose_mood(light_bucket, wind_bucket)

    primary = random.choice(MOOD_LINES[mood])
    lines = [primary]
    if random.random() < 0.85:
        lines.append(HUE_LINES[hue_bucket])
    return " ".join(lines)


def _draw_thanks(screen, font, surfs, t: float) -> None:
    # Warm cream/gold background that pulses gently
    pulse = 0.5 + 0.5 * math.sin(t * 4.0)
    bg_r = int(248 + pulse * 7)
    bg_g = int(240 + pulse * 8)
    bg_b = int(210 + pulse * 20)
    screen.fill((bg_r, bg_g, bg_b))

    cx, cy = WIDTH // 2, HEIGHT // 2

    if font is None:
        return

    # ── "THANK YOU!" — large, bouncy ─────────────────────────────────────────
    bounce = int(6 * math.sin(t * 5.5))
    ty_surf = font.render("THANK YOU!", True, (34, 28, 18))
    ty_rect = ty_surf.get_rect(center=(cx, cy - 46 + bounce))
    screen.blit(ty_surf, ty_rect)

    # ── Emotion line ──────────────────────────────────────────────────────────
    emotion_text = state.plant_emotion or "I am still catching my breath."
    color = (80, 60, 20)

    # Use a slightly smaller font for the emotion — render manually scaled
    try:
        small_font = pygame.font.SysFont("Avenir Next", 28) or pygame.font.SysFont("Arial", 28)
    except Exception:
        small_font = font

    wrapped = _wrap_text(small_font, emotion_text, int(WIDTH * 0.82))
    line_height = small_font.get_linesize()
    total_height = line_height * len(wrapped)
    top_y = cy + 24 - total_height // 2
    em_rect = pygame.Rect(cx, cy + 24, 1, 1)
    for idx, line in enumerate(wrapped):
        em_surf = small_font.render(line, True, color)
        line_rect = em_surf.get_rect(center=(cx, top_y + idx * line_height + line_height // 2))
        screen.blit(em_surf, line_rect)
        em_rect = em_rect.union(line_rect)

    # Soft underline flourish
    line_y = em_rect.bottom + 6
    line_w = em_rect.width + 20
    pygame.draw.line(screen, (180, 160, 100), (cx - line_w // 2, line_y), (cx + line_w // 2, line_y), 2)

    # ── Small leaf decorations either side ───────────────────────────────────
    leaf_color = (80, 150, 80)
    for side in (-1, 1):
        lx = cx + side * (em_rect.width // 2 + 28)
        ly = cy + 24
        sway = int(4 * math.sin(t * 3.2 + side))
        pts = [
            (lx, ly + sway),
            (lx + side * 14, ly - 10 + sway),
            (lx + side * 8, ly + 12 + sway),
        ]
        pygame.draw.polygon(screen, leaf_color, pts)

    _draw_phase_label(screen, "the plant thanks you...", font, surfs, t)


# ─── Pre-allocated surface pool ──────────────────────────────────────────────

class Surfaces:
    """All reusable pygame Surfaces, allocated once at renderer startup."""
    def __init__(self):
        # Opaque fade overlay (no alpha channel needed — uses set_alpha instead)
        self.fade          = pygame.Surface((WIDTH, HEIGHT))
        # Full-screen SRCALPHA overlays
        self.flash         = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.bar_flash     = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.particle_layer = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.ripple        = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.highlight     = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.orbit_layer   = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.glow_layer    = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        # Badge surface is variable-sized; start as None, lazily allocated once
        self.badge         = None


# ─── Pygame render loop ───────────────────────────────────────────────────────

async def _run_pygame_renderer() -> None:
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Botanical Beats Visualizer")

    font = None
    try:
        pygame.font.init()
        font = pygame.font.SysFont("Avenir Next", 42)
        if font is None:
            font = pygame.font.SysFont("Arial", 42)
    except Exception as exc:
        print(f"[viz] font unavailable: {exc}")

    # Allocate all surfaces once here — never inside draw functions.
    surfs = Surfaces()

    clock = pygame.time.Clock()
    t = 0.0
    thanks_entered_at: float = 0.0
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        dt = max(0.0001, clock.get_time() / 1000.0)
        t += dt

        # Decay energies each frame.
        state.hit_energy   *= 0.93
        state.note_energy  *= 0.94
        state.snare_energy *= 0.92
        state.audio_level  *= 0.90

        # Decay plant physics.
        state.plant_bounce = max(0.0, state.plant_bounce - dt * 5.5)
        state.plant_squish = max(0.0, state.plant_squish - dt * 6.0)
        state.plant_wiggle *= 0.96

        # Composite amplitude signal.
        amplitude = max(state.audio_level, state.hit_energy * 0.7, state.energy * 0.5)
        hue = (state.frozen_hue * 0.65 + state.hue * 0.35) % 1.0
        brightness = state.frozen_light

        # Auto-transition from thanks → idle after 10 s (long enough to read the emotion).
        if state.phase == "thanks":
            if thanks_entered_at == 0.0:
                thanks_entered_at = time.monotonic()
                # Generate mood text once at thanks entry.
                state.peak_amplitude = max(state.peak_amplitude, amplitude)
                state.plant_emotion = _build_mood_message(
                    state.frozen_light,
                    state.frozen_fan,
                    hue,
                )
                print(f"[viz] plant emotion: {state.plant_emotion}")
            state.peak_amplitude = max(state.peak_amplitude, amplitude)
            if time.monotonic() - thanks_entered_at > 10.0:
                state.phase = "idle"
                thanks_entered_at = 0.0
                # Reset session stats for next performance
                state.total_hits = 0
                state.total_notes = 0
                state.total_bars = 0
                state.peak_amplitude = 0.0
        else:
            thanks_entered_at = 0.0

        if state.phase == "idle":
            _draw_idle(screen, font, surfs, t, amplitude, hue, brightness)
        elif state.phase == "talking":
            # Talking uses the orb scene on a light background.
            _draw_talking(screen, font, surfs, t, amplitude, hue)
        elif state.phase == "listening":
            # Listening uses the radial analyzer scene.
            _draw_listening(screen, font, surfs, t)
        elif state.phase == "listenting":
            # Follow-up typo-address phase uses the radial analyzer.
            _draw_listening(screen, font, surfs, t)
        elif state.phase == "thanks":
            _draw_thanks(screen, font, surfs, t)
        else:
            r, g, b = _hsv_rgb(hue, 0.18, 0.92)
            screen.fill((r, g, b))
            _draw_phase_label(screen, state.phase.upper(), font, surfs)

        pygame.display.flip()
        clock.tick(FPS)
        await asyncio.sleep(0)

    pygame.quit()


# ─── Console fallback ─────────────────────────────────────────────────────────

async def _run_console_renderer() -> None:
    print("[viz] pygame unavailable — console renderer active.")
    while True:
        amplitude = max(state.audio_level, state.hit_energy * 0.7)
        print(f"[viz] phase={state.phase:12s}  hue={state.hue:.2f}  amp={amplitude:.2f}")
        await asyncio.sleep(1.0)


# ─── OSC server + entry point ─────────────────────────────────────────────────

async def main() -> None:
    dispatcher = Dispatcher()

    # Phase transitions.
    dispatcher.map("/state/idle",       _set_phase("idle"))
    dispatcher.map("/state/talking",    _set_phase("talking"))
    dispatcher.map("/state/listening",  _set_phase("listening"))
    dispatcher.map("/state/listenting", _set_phase("listenting"))
    dispatcher.map("/state/thanks",     _set_phase("thanks"))

    # Continuous modulation.
    dispatcher.map("/viz/mod/hue",     _mod_hue)
    dispatcher.map("/viz/mod/energy",  _mod_energy)
    dispatcher.map("/viz/audio/pulse", _audio_pulse)
    dispatcher.map("/frozen/hue",      _frozen_hue)
    dispatcher.map("/frozen/light",    _frozen_light)
    dispatcher.map("/frozen/fan",      _frozen_fan)

    # Musical cues.
    dispatcher.map("/cue/snare", _cue_snare)
    dispatcher.map("/cue/hit",   _cue_hit)
    dispatcher.map("/cue/note",  _cue_note)
    dispatcher.map("/cue/bar",   _cue_bar)

    loop = asyncio.get_event_loop()
    server = AsyncIOOSCUDPServer((OSC_HOST, OSC_PORT), dispatcher, loop)
    transport, _ = await server.create_serve_endpoint()
    print(f"[viz] OSC server listening on {OSC_HOST}:{OSC_PORT}")

    try:
        if _HAS_PYGAME:
            try:
                await _run_pygame_renderer()
            except Exception as exc:
                print(f"[viz] pygame runtime error, falling back to console: {exc}")
                await _run_console_renderer()
        else:
            await _run_console_renderer()
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
