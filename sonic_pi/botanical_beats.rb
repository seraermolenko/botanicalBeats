# Botanical Beats - integrated trigger engine + visual sync

use_osc_logging false
use_bpm 100
set_volume! 2.2

set :viz_host, "127.0.0.1"
set :viz_port, 9001

set :phase, :idle
set :ambient_vol, 1.0
set :motion, 0.5
set :hue, 0.5
set :brightness, 0.5
set :density, 0.5
set :sparkle, 0.5
set :energy, 0.5
set :beat_count, 0
set :bar_count, 1

# ---------------- Helpers ----------------
define :clamp01 do |v|
  x = v.to_f
  return 0.0 if x < 0.0
  return 1.0 if x > 1.0
  x
end

define :viz_audio do |amp|
  osc get(:viz_host), get(:viz_port), "/viz/audio/pulse", clamp01(amp)
end

define :viz_hit do |name, amp|
  osc get(:viz_host), get(:viz_port), "/cue/hit", name, get(:beat_count), get(:bar_count), amp
end

define :viz_note do |n, dur, amp|
  osc get(:viz_host), get(:viz_port), "/cue/note", n, dur, get(:beat_count), get(:bar_count), amp
end

define :viz_snare do |amp|
  osc get(:viz_host), get(:viz_port), "/cue/snare", get(:beat_count), get(:bar_count), amp
end

define :play_touch_event do |velocity=0.9|
  v = clamp01(velocity || 0.9)
  main_amp = 0.9 * v

  # Always play a clear, punchy touch sound.
  sample :elec_snare, amp: main_amp, cutoff: 112
  sample :perc_snap, amp: 0.35 * v, rate: 1.15

  use_synth :pluck
  n = scale(:C4, :minor_pentatonic).choose
  play n, amp: 0.22 * v, release: 0.28

  # Drive visuals at the same moment as the sound.
  viz_audio(main_amp)
  viz_hit("touch", main_amp)
  viz_snare(main_amp)
  viz_note(n, 0.28, 0.22 * v)
end

# Shared musical phrase so both /trigger/response and state-bridge can use it.
define :play_response_phrase do |motion, hue, brightness, seed|
  use_random_seed seed.to_i

  the_scale = case hue
              when 0.0..0.25 then :major
              when 0.25..0.5 then :mixolydian
              when 0.5..0.75 then :minor
              else :phrygian
              end

  roots = [:C, :D, :E, :F, :G, :A, :B]
  root = roots[(seed.to_i % 7)]

  base_octave = 3 + (brightness * 2).to_i
  root_note = (root.to_s + base_octave.to_s).to_sym

  synth_choice = if hue < 0.33
                   [:piano, :pluck, :kalimba].choose
                 elsif hue < 0.66
                   [:prophet, :saw, :tb303].choose
                 else
                   [:hollow, :dark_ambience, :blade].choose
                 end

  num_notes = (4 + (motion * 12)).to_i
  base_sleep = [0.5 - (motion * 0.3), 0.15].max

  use_synth synth_choice
  notes = scale(root_note, the_scale, num_octaves: 2)

  num_notes.times do
    n = notes.choose
    amp = rrand(0.25, 0.65)
    dur = rrand(0.1, 0.4 + (1.0 - motion) * 0.3)

    play n, amp: amp, attack: 0.05, sustain: dur, release: dur * 2
    viz_audio(amp)
    viz_note(n, dur, amp)

    if one_in(4)
      sleep base_sleep * 2
    else
      sleep base_sleep
    end
  end

  use_synth :hollow
  tail_amp = 0.18
  play chord(root_note, :m7), amp: tail_amp, attack: 1, release: 3
  viz_audio(tail_amp)
end

# ---------------- OSC Receivers ----------------
live_loop :rx_state do
  use_real_time
  a, _v = sync "/osc*/state/*"
  if a.include?("/state/idle")
    set :phase, :idle
  elsif a.include?("/state/talking")
    set :phase, :talking
  elsif a.include?("/state/listening")
    set :phase, :listening
  elsif a.include?("/state/thanks")
    set :phase, :thanks
  end
end

live_loop :rx_param do
  use_real_time
  addr, *vals = sync "/osc*/param/*"
  v = clamp01(vals[0] || 0.5)
  if addr.include?("/param/energy")
    set :energy, v
  elsif addr.include?("/param/density")
    set :density, v
  elsif addr.include?("/param/sparkle")
    set :sparkle, v
  end
end

live_loop :rx_sensor_motion do
  use_real_time
  _a, m = sync "/osc*/sensor/motion"
  set :motion, clamp01(m || 0.0)
end

live_loop :rx_sensor_rgb do
  use_real_time
  _a, *vals = sync "/osc*/sensor/rgb"
  if vals[0].is_a?(Array)
    r, g, b = vals[0]
  else
    r, g, b = vals
  end
  r = clamp01(r || 0.5)
  g = clamp01(g || 0.5)
  b = clamp01(b || 0.5)
  set :hue, r
  set :brightness, (r + g + b) / 3.0
end

# ---------------- Trigger APIs (as requested) ----------------
live_loop :ambient_listener do
  use_real_time
  msg = sync "/osc*/trigger/ambient"
  set :ambient_vol, clamp01(msg[0] || 0.0)
end

live_loop :touch_hits_trigger do
  use_real_time
  msg = sync "/osc*/trigger/touch"
  velocity = clamp01(msg[0] || 0.9)
  play_touch_event(velocity)
  puts "touch trigger event v=#{velocity.round(2)}"
end

live_loop :listening_indicator_trigger do
  use_real_time
  sync "/osc*/trigger/listening"
  use_synth :sine
  play :G5, amp: 0.18, attack: 0.1, release: 0.5
  viz_audio(0.18)
  viz_note(79, 0.5, 0.18)
  sleep 0.3
  play :C6, amp: 0.12, attack: 0.1, release: 0.3
  viz_audio(0.12)
  viz_note(84, 0.3, 0.12)
end

live_loop :plant_response_trigger do
  use_real_time
  msg = sync "/osc*/trigger/response"
  motion = clamp01(msg[0] || 0.5)
  hue = clamp01(msg[1] || 0.5)
  brightness = clamp01(msg[2] || 0.5)
  seed = (msg[3] || 0).to_i

  play_response_phrase(motion, hue, brightness, seed)
end

# ---------------- Compatibility Bridge (current controller) ----------------
# Ambient on only in idle.
live_loop :ambient_bridge do
  if get(:phase) == :idle
    set :ambient_vol, 1.0
  else
    set :ambient_vol, 0.0
  end
  sleep 0.1
end

# Touch from current controller path.
live_loop :touch_hits_from_sensor do
  use_real_time
  sync "/osc*/sensor/touch"
  play_touch_event(0.95)
  puts "touch sensor event"
end

# Listening entry chime on phase transition.
live_loop :listening_indicator_from_state do
  use_real_time
  sync "/osc*/state/listening"
  use_synth :sine
  play :G5, amp: 0.18, attack: 0.1, release: 0.5
  viz_audio(0.18)
  viz_note(79, 0.5, 0.18)
  sleep 0.3
  play :C6, amp: 0.12, attack: 0.1, release: 0.3
  viz_audio(0.12)
  viz_note(84, 0.3, 0.12)
end

# Main listening response driven from current state/params/sensors.
live_loop :plant_response_from_state do
  if get(:phase) == :listening
    motion = clamp01(get(:motion) || 0.5)
    hue = clamp01(get(:hue) || 0.5)
    brightness = clamp01(get(:brightness) || 0.5)
    seed = ((get(:density) || 0.5) * 1000 + (get(:sparkle) || 0.5) * 10000).to_i
    play_response_phrase(motion, hue, brightness, seed)
  else
    sleep 0.1
  end
end

# Ambient generator layer
live_loop :ambient do
  vol = get(:ambient_vol) || 0.0
  if vol > 0
    use_synth :hollow
    n = chord(:C3, :m7).choose
    play n, amp: 0.18 * vol, attack: 2, sustain: 2, release: 3
    viz_audio(0.16 * vol)
    viz_note(n, 3.0, 0.16 * vol)
    sleep [2, 3, 4].choose

    if one_in(3)
      use_synth :dark_ambience
      play :C2, amp: 0.12 * vol, attack: 3, release: 4
      viz_audio(0.12 * vol)
    end
  else
    sleep 1
  end
end

# Beat/bar clock for visual timing continuity
live_loop :clock do
  beat = get(:beat_count) + 1
  bar = ((beat - 1) / 4).floor + 1
  set :beat_count, beat
  set :bar_count, bar
  osc get(:viz_host), get(:viz_port), "/cue/bar", bar if (beat % 4) == 1
  sleep 0.5
end
