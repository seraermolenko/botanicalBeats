# System Architecture

## Roles

- Pi Controller: installation authority (state, hardware, sensors)
- Sonic Pi: musical authority (clock, sequencing, beat-grid cues)
- Visualizer: render authority (scene graph + reactive events)

## State machine

`IDLE -> TALKING -> LISTENING -> THANKS -> IDLE`

- `IDLE`
  - Pots update fan/light in real time
  - Sonic Pi plays idle snare and emits `/cue/snare`
- `TALKING` (`3s`)
  - Pot values frozen
  - Visualizer: black + talking text
  - Sonic Pi leaves idle snare loop
- `LISTENING` (`10s`)
  - Pi streams sensor/derived params
  - Sonic Pi uses latest params on each beat subdivision
  - Sonic Pi emits matching `/cue/*` events for each scheduled sound
- `THANKS` (`3s`)
  - Visualizer: thanks scene
  - Optional hardware fade then off

## Timing model

- Soft real-time domain: Pi sensor/control stream (30 Hz target)
- Musical real-time domain: Sonic Pi scheduler (beat-accurate)
- Synchronization rule: visuals for hits/notes are triggered from Sonic Pi cues only

## Boot flow

1. Start visualizer listener
2. Start Pi controller
3. Run Sonic Pi script
4. Pi enters IDLE and broadcasts `/state/idle`

## Failure strategy

- If Pi sensor stream pauses, Sonic Pi continues on last known params.
- If visualizer disconnects, audio remains correct; cues are best-effort UDP.
- If Sonic Pi stops, Pi still runs hardware and phase logic.
