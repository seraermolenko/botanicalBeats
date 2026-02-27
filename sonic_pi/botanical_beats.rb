# Sonic Pi master clock + cue emitter for Botanical Beats.
# Receives Pi state/params over OSC and emits beat-accurate cues to visualizer.

use_bpm 100

set :phase, :idle
set :energy, 0.5
set :density, 0.5
set :sparkle, 0.5
set :motion, 0.5
set :rgb, [0.5, 0.5, 0.5]

set :beat_count, 0
set :bar_count, 1

# Change this to visualizer host/port
set :viz_host, "127.0.0.1"
set :viz_port, 9001

live_loop :rx_state do
  use_real_time
  a, _ = sync "/osc*/state/*"
  # a is like "/osc:127.0.0.1:xxxxx/state/listening"
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

live_loop :rx_params do
  use_real_time
  addr, *vals = sync "/osc*/param/*"
  if addr.include?("/param/energy")
    set :energy, vals[0]
  elsif addr.include?("/param/density")
    set :density, vals[0]
  elsif addr.include?("/param/sparkle")
    set :sparkle, vals[0]
  end
end

live_loop :rx_sensor_motion do
  use_real_time
  _addr, motion = sync "/osc*/sensor/motion"
  set :motion, motion
end

live_loop :rx_sensor_rgb do
  use_real_time
  _addr, r, g, b = sync "/osc*/sensor/rgb"
  set :rgb, [r, g, b]
end

live_loop :clock do
  beat = get(:beat_count) + 1
  bar = ((beat - 1) / 4).floor + 1
  set :beat_count, beat
  set :bar_count, bar

  osc get(:viz_host), get(:viz_port), "/cue/bar", bar if (beat % 4) == 1

  phase = get(:phase)

  if phase == :idle
    sample :sn_dub, amp: 0.8
    osc get(:viz_host), get(:viz_port), "/cue/snare", beat, bar, 0.8
  elsif phase == :listening
    e = get(:energy) || 0.5
    d = get(:density) || 0.5
    s = get(:sparkle) || 0.5

    vel = 0.4 + e * 0.6
    if one_in((1.0 + (1.0 - d) * 7.0).round)
      sample :bd_tek, amp: vel
      osc get(:viz_host), get(:viz_port), "/cue/hit", "kick", beat, bar, vel
    end

    with_synth :blade do
      n = scale(:e3, :minor_pentatonic).choose + (s * 7).floor
      dur = [0.25, 0.5].choose
      play n, release: dur, amp: vel
      osc get(:viz_host), get(:viz_port), "/cue/note", n, dur, beat, bar, vel
    end
  end

  sleep 0.5 # 1/8-note grid at 100 BPM
end
