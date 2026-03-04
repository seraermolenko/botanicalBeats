# sonic_pi/botanical_beats.rb
# ─────────────────────────────────────────────────────────────────
# Botanical Beats — Sonic Pi Sound Engine
#
# This script runs inside Sonic Pi. It listens for OSC messages
# from the Python orchestrator and generates all audio.
#
# OSC inputs from Python:
#   /state/idle, /state/talking, /state/listening, /state/thanks
#   /sensor/touch, /sensor/motion, /sensor/rgb
#   /param/energy, /param/density, /param/sparkle
#
# Load this script in Sonic Pi, then run the Python main.py.
# ─────────────────────────────────────────────────────────────────

use_osc_logging false

# Shared state populated by OSC listeners.
set :bb_state, :idle
set :bb_motion, 0.0
set :bb_hue, 0.5
set :bb_brightness, 0.5
set :bb_energy, 0.0
set :bb_density, 0.0
set :bb_sparkle, 0.0

define :clamp01 do |v|
  [[v.to_f, 0.0].max, 1.0].min
end

# ═══════════════════════════════════════════════════════════════════
# OSC LISTENERS
# ═══════════════════════════════════════════════════════════════════

live_loop :state_idle_listener do
  sync "/osc*/state/idle"
  set :bb_state, :idle
end

live_loop :state_talking_listener do
  sync "/osc*/state/talking"
  set :bb_state, :talking
end

live_loop :state_listening_listener do
  sync "/osc*/state/listening"
  set :bb_state, :listening
end

live_loop :state_thanks_listener do
  sync "/osc*/state/thanks"
  set :bb_state, :thanks
end

live_loop :sensor_motion_listener do
  msg = sync "/osc*/sensor/motion"
  set :bb_motion, clamp01(msg[0] || 0.0)
end

live_loop :sensor_rgb_listener do
  msg = sync "/osc*/sensor/rgb"
  r = clamp01(msg[0] || 0.0)
  g = clamp01(msg[1] || 0.0)
  b = clamp01(msg[2] || 0.0)
  # Convert RGB roughly into hue + perceived brightness.
  maxc = [r, g, b].max
  minc = [r, g, b].min
  delta = maxc - minc
  hue = if delta <= 0.0001
          0.5
        elsif maxc == r
          ((g - b) / delta) % 6.0
        elsif maxc == g
          ((b - r) / delta) + 2.0
        else
          ((r - g) / delta) + 4.0
        end
  hue = (hue / 6.0) % 1.0
  brightness = (0.2126 * r + 0.7152 * g + 0.0722 * b)
  set :bb_hue, clamp01(hue)
  set :bb_brightness, clamp01(brightness)
end

live_loop :param_energy_listener do
  msg = sync "/osc*/param/energy"
  set :bb_energy, clamp01(msg[0] || 0.0)
end

live_loop :param_density_listener do
  msg = sync "/osc*/param/density"
  set :bb_density, clamp01(msg[0] || 0.0)
end

live_loop :param_sparkle_listener do
  msg = sync "/osc*/param/sparkle"
  set :bb_sparkle, clamp01(msg[0] || 0.0)
end

# ═══════════════════════════════════════════════════════════════════
# AMBIENT BACKGROUND (plays in IDLE)
# ═══════════════════════════════════════════════════════════════════

live_loop :ambient do
  state = get(:bb_state)
  vol = state == :idle ? 1.0 : 0.0
  if vol > 0
    use_synth :piano
    s = scale(:C4, :major_pentatonic, num_octaves: 2)
    [3, 4, 5].choose.times do
      play s.choose, amp: 0.3 * vol, attack: 0.02, release: 2.0
      sleep [0.5, 0.75, 1.0].choose
    end
    sleep [2, 3, 4].choose
  else
    sleep 1
  end
end


# ═══════════════════════════════════════════════════════════════════
# TOUCH HITS
# Triggered by OSC /sensor/touch [velocity]
# Plays a short percussive sound layered over everything else.
# ═══════════════════════════════════════════════════════════════════

live_loop :touch_hits do
  msg = sync "/osc*/sensor/touch"
  velocity = clamp01(msg[0] || 1.0)

  hit_type = [:drum_tom_lo_hard, :drum_tom_mid_hard, :drum_snare_soft,
              :drum_cymbal_soft, :perc_snap, :perc_till].choose

  sample hit_type, amp: velocity * 0.6, rate: rrand(0.8, 1.2)

  use_synth :pluck
  play scale(:C4, :minor_pentatonic).choose, amp: velocity * 0.2, release: 0.3
end


# ═══════════════════════════════════════════════════════════════════
# LISTENING INDICATOR
# Subtle sound while state=listening.
# ═══════════════════════════════════════════════════════════════════

live_loop :listening_indicator do
  if get(:bb_state) == :listening
    use_synth :sine
    play :G5, amp: 0.12, attack: 0.08, release: 0.35
    sleep 0.25
    play :C6, amp: 0.08, attack: 0.08, release: 0.25
    sleep 0.35
  else
    sleep 0.2
  end
end


# ═══════════════════════════════════════════════════════════════════
# PLANT RESPONSE
# Main response phrase generator. Runs only while listening state is active.
# ═══════════════════════════════════════════════════════════════════

live_loop :plant_response do
  unless get(:bb_state) == :listening
    sleep 0.2
    next
  end

  motion = clamp01(get(:bb_motion) || 0.0)
  hue = clamp01(get(:bb_hue) || 0.5)
  brightness = clamp01(get(:bb_brightness) || 0.5)
  energy = clamp01(get(:bb_energy) || 0.0)
  density = clamp01(get(:bb_density) || 0.0)
  sparkle = clamp01(get(:bb_sparkle) || 0.0)

  # Stable-ish seed from current control values.
  seed = (
    motion * 1000 +
    hue * 2000 +
    brightness * 3000 +
    energy * 4000 +
    density * 5000 +
    sparkle * 6000
  ).to_i
  use_random_seed seed

  the_scale = case hue
              when 0.0..0.25 then :major_pentatonic
              when 0.25..0.5 then :lydian
              when 0.5..0.75 then :dorian
              else :major_pentatonic
              end

  roots = [:C, :D, :E, :F, :G, :A, :B]
  root = roots[(seed % 7)]
  base_octave = 4 + (brightness * 1).to_i
  root_note = (root.to_s + base_octave.to_s).to_sym

  synth_choice = if hue < 0.33
                   [:kalimba, :pluck, :piano].choose
                 elsif hue < 0.66
                   [:blade, :pluck, :sine].choose
                 else
                   [:hollow, :blade, :pretty_bell].choose
                 end

  num_notes = (3 + (motion * 8) + (density * 4)).to_i
  num_notes = [[num_notes, 3].max, 14].min
  base_sleep = 0.5 - (motion * 0.25) - (density * 0.12)
  base_sleep = [base_sleep, 0.12].max
  use_synth synth_choice

  notes = scale(root_note, the_scale, num_octaves: 2)

  num_notes.times do
    break unless get(:bb_state) == :listening

    note = notes.choose
    amp = rrand(0.18, 0.38 + energy * 0.28)
    dur = rrand(0.1, 0.4 + (1.0 - motion) * 0.3)

    play note, amp: amp, attack: 0.05, sustain: dur, release: dur * 2

    if one_in(4 + (sparkle * 4).to_i)
      sleep base_sleep * 2
    else
      sleep base_sleep
    end
  end

  if get(:bb_state) == :listening
    use_synth :hollow
    play chord(root_note, :major7), amp: 0.14 + energy * 0.08, attack: 0.7, release: 2.5
  end
end
