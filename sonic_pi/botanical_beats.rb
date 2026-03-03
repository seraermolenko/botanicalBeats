# Sonic Pi master clock + cue emitter for Botanical Beats.
# Receives Pi state/params over OSC and emits beat-accurate cues to visualizer.

use_bpm 100

set :phase, :idle
set :energy, 0.5
set :density, 0.5
set :sparkle, 0.5
set :motion, 0.5
set :rgb, [0.5, 0.5, 0.5]
set :touch_last_at, 0.0

set :beat_count, 0
set :bar_count, 1

# Change this to visualizer host/port
set :viz_host, "127.0.0.1"
set :viz_port, 9001

define :clamp01 do |v|
  return 0.0 if v.nil?
  v = v.to_f
  return 0.0 if v < 0.0
  return 1.0 if v > 1.0
  v
end

define :first_number do |vals, fallback=0.5|
  return fallback if vals.nil? || vals.length == 0
  v = vals[0]
  if v.is_a?(Array)
    return fallback if v.length == 0
    return v[0].to_f
  end
  v.to_f
end

define :rgb_from_payload do |vals|
  if vals.length == 1 && vals[0].is_a?(Array)
    arr = vals[0]
    r = arr[0] || 0.5
    g = arr[1] || 0.5
    b = arr[2] || 0.5
    return [clamp01(r), clamp01(g), clamp01(b)]
  end
  r = vals[0] || 0.5
  g = vals[1] || 0.5
  b = vals[2] || 0.5
  [clamp01(r), clamp01(g), clamp01(b)]
end

define :lerp do |a, b, t|
  a + (b - a) * t
end

live_loop :rx_state_idle do
  use_real_time
  sync "/osc*/state/idle"
  set :phase, :idle
  puts "state: idle"
end

live_loop :rx_state_talking do
  use_real_time
  sync "/osc*/state/talking"
  set :phase, :talking
  puts "state: talking"
end

live_loop :rx_state_listening do
  use_real_time
  sync "/osc*/state/listening"
  set :phase, :listening
  puts "state: listening"
end

live_loop :rx_state_thanks do
  use_real_time
  sync "/osc*/state/thanks"
  set :phase, :thanks
  puts "state: #{get(:phase)}"
end

live_loop :rx_param_energy do
  use_real_time
  vals = sync "/osc*/param/energy"
  next unless get(:phase) == :listening
  e = clamp01(first_number(vals, 0.5))
  # Smooth incoming control to avoid jumpy sound/visual behavior.
  set :energy, lerp(get(:energy) || 0.5, e, 0.35)
end

live_loop :rx_param_density do
  use_real_time
  vals = sync "/osc*/param/density"
  next unless get(:phase) == :listening
  d = clamp01(first_number(vals, 0.5))
  set :density, lerp(get(:density) || 0.5, d, 0.35)
end

live_loop :rx_param_sparkle do
  use_real_time
  vals = sync "/osc*/param/sparkle"
  next unless get(:phase) == :listening
  s = clamp01(first_number(vals, 0.5))
  set :sparkle, lerp(get(:sparkle) || 0.5, s, 0.35)
end

live_loop :rx_sensor_motion do
  use_real_time
  vals = sync "/osc*/sensor/motion"
  motion = clamp01(first_number(vals, 0.0))
  set :motion, lerp(get(:motion) || 0.0, motion, 0.4)
end

live_loop :rx_sensor_touch do
  use_real_time
  sync "/osc*/sensor/touch"
  if get(:phase) == :idle
    amp = 0.78
    with_fx :reverb, room: 0.5, mix: 0.25 do
      sample :elec_snare, amp: amp, cutoff: 108
    end
    osc get(:viz_host), get(:viz_port), "/cue/snare", get(:beat_count), get(:bar_count), amp
  else
    amp = 0.72
    with_fx :reverb, room: 0.55, mix: 0.28 do
      sample :elec_snare, amp: amp, cutoff: 112
    end
    osc get(:viz_host), get(:viz_port), "/cue/hit", "touch", get(:beat_count), get(:bar_count), amp
  end
  set :touch_last_at, vt
  puts "touch pulse"
end

live_loop :rx_sensor_rgb do
  use_real_time
  vals = sync "/osc*/sensor/rgb"
  r, g, b = rgb_from_payload(vals)
  set :rgb, [r, g, b]
end

live_loop :rx_debug do
  sleep 1
  puts "phase=#{get(:phase)} e=#{(get(:energy) || 0).round(2)} d=#{(get(:density) || 0).round(2)} s=#{(get(:sparkle) || 0).round(2)} m=#{(get(:motion) || 0).round(2)}"
end

live_loop :clock do
  beat = get(:beat_count) + 1
  bar = ((beat - 1) / 4).floor + 1
  set :beat_count, beat
  set :bar_count, bar

  osc get(:viz_host), get(:viz_port), "/cue/bar", bar if (beat % 4) == 1

  phase = get(:phase)

  if phase == :idle
    # Keep idle minimal: gentle pulse every half bar.
    if (beat % 2) == 1
      amp = 0.34
      sample :perc_snap, amp: amp, cutoff: 95
      osc get(:viz_host), get(:viz_port), "/cue/snare", beat, bar, amp
    end
  elsif phase == :listening
    e = get(:energy) || 0.5
    d = get(:density) || 0.5
    s = get(:sparkle) || 0.5
    m = get(:motion) || 0.0
    r, g, b = get(:rgb) || [0.5, 0.5, 0.5]

    master_amp = 0.36 + e * 0.52
    cutoff = 75 + e * 35
    kick_gate = 1.0 + (1.0 - d) * 7.0
    note_gate = 1.0 + (1.0 - s) * 4.0

    if one_in(kick_gate.round)
      k_amp = master_amp * (0.7 + 0.3 * m)
      sample :bd_tek, amp: k_amp, cutoff: cutoff
      osc get(:viz_host), get(:viz_port), "/cue/hit", "kick", beat, bar, k_amp
    end

    if one_in(note_gate.round)
      base = (r > b) ? :e3 : :a3
      sc = scale(base, :minor_pentatonic, num_octaves: 2)
      idx = ((g * (sc.length - 1)).round + (s * 3).round) % sc.length
      n = sc[idx]
      dur = 0.2 + s * 0.55
      n_amp = master_amp * (0.65 + s * 0.35)

      with_fx :reverb, room: 0.75, mix: 0.32 do
        with_fx :lpf, cutoff: cutoff + 12 do
          with_synth :prophet do
            play n, release: dur, amp: n_amp
          end
        end
      end
      osc get(:viz_host), get(:viz_port), "/cue/note", n, dur, beat, bar, n_amp
    end

    # Gentle high sparkle layer, thinned out to avoid clutter.
    if s > 0.62 && one_in(5)
      bell_n = 72 + (s * 7).floor
      b_amp = 0.10 + s * 0.16
      with_fx :reverb, room: 0.9, mix: 0.45 do
        with_synth :pretty_bell do
          play bell_n, release: 0.35 + s * 0.35, amp: b_amp
        end
      end
      osc get(:viz_host), get(:viz_port), "/cue/note", bell_n, 0.35, beat, bar, b_amp
    end
  end

  sleep 0.5 # 1/8-note grid at 100 BPM
end
