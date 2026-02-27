# OSC Contract

This contract separates low-rate installation state from beat-accurate cue timing.

## 1) Pi -> Sonic Pi (state + params)

- `/state/idle`
- `/state/talking`
- `/state/listening`
- `/state/thanks`

Frozen values (on button press and optionally at phase edges):

- `/frozen/fan <float0to1>`
- `/frozen/hue <float0to1>`
- `/frozen/light <float0to1>`

Continuous data (during LISTENING):

- `/sensor/motion <float0to1>`
- `/sensor/rgb <r0to1> <g0to1> <b0to1>`
- `/param/energy <float0to1>`
- `/param/density <float0to1>`
- `/param/sparkle <float0to1>`

`/sensor/motion` should come from camera motion intensity normalized to `0..1`.

## 2) Pi -> Visualizer (state + optional continuous modulation)

- `/state/idle`
- `/state/talking`
- `/state/listening`
- `/state/thanks`

Optional modulation (not beat triggers):

- `/viz/mod/hue <float0to1>`
- `/viz/mod/energy <float0to1>`

## 3) Sonic Pi -> Visualizer (beat-accurate cues, critical)

- `/cue/snare <beat> <bar> <vel>`
- `/cue/hit <name> <beat> <bar> <vel>`
- `/cue/note <midi> <dur_beats> <beat> <bar> <vel>`
- `/cue/bar <bar>`
- `/cue/section <symbol_or_text>`

These messages are sent exactly when Sonic Pi schedules sound events.

## Recommended rates

- Pi param push during LISTENING: `30 Hz`
- Pi param push outside LISTENING: `2 Hz` or off
- Sonic Pi cue push: rhythmic grid (`1/8` or `1/16` notes), plus each event

## Reliability guidelines

- Keep OSC payloads small and normalized (`0..1`) where possible.
- Use a local network or same machine for Sonic Pi + visualizer.
- Avoid routing beat triggers through Pi; they must originate in Sonic Pi.
