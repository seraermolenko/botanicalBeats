# Botanical Beats

Raspberry Pi runs the installation state machine and hardware I/O.
Sonic Pi is the musical timing authority and emits beat-accurate OSC cues.
Visualizer runs continuously and changes scenes from state + cue messages.

## Architecture

- Pi controller (`pi_controller/main.py`)
  - Reads pots + button + sensors
  - Controls fan/light hardware in `IDLE`
  - Freezes pot values on start button
  - Runs state machine timings (`TALKING=3s`, `LISTENING=10s`, `THANKS=3s`)
  - Sends OSC state + parameters to Sonic Pi and Visualizer
- Sonic Pi (`sonic_pi/botanical_beats.rb`)
  - Receives state/params from Pi
  - Runs beat/bar clock
  - In `IDLE`, plays snare loop and sends `/cue/snare`
  - In `LISTENING`, schedules sound on beat and sends matching visual cues
- Visualizer (`visualizer/main.py`)
  - Always rendering (ambient by default)
  - Black phase screens with text:
    - `...talking to plant`
    - `..listening to plant`
    - `thanks for listening`
  - Scene switches from `/state/*`
  - Triggered animations from Sonic Pi cue events (`/cue/*`)

## OSC Endpoints (default)

- Pi controller listen: `127.0.0.1:9000` (optional external control)
- Sonic Pi listen: `127.0.0.1:4560`
- Visualizer listen: `127.0.0.1:9001`

Update in `docs/osc_contract.md` and `pi_controller/config.py` as needed.

## Run order

1. Start visualizer:
   - `python -m visualizer.main`
2. Start Pi controller:
   - `python -m pi_controller.main`
3. Start Sonic Pi and paste/run `sonic_pi/botanical_beats.rb`

## Notes

- Camera motion detection is integrated in `pi_controller/sensors.py` (Picamera2 + OpenCV).
- If camera dependencies are unavailable, motion falls back to simulated values.
- TCS34725 RGB sensor + ADS1115 pots + fan PWM + LED output are wired in code with fallback to simulation.
- For tight sync, treat Sonic Pi cues as visual trigger source during rhythmic sections.
- Start button defaults to `GPIO23`; change in `pi_controller/config.py` if needed.
- Enable real Pi hardware mode with:
  - `export BOTANICAL_USE_PI_HARDWARE=1`

## Keyboard testing mode (no hardware)

Enable keyboard-driven test input:

- `export BOTANICAL_USE_KEYBOARD=1`
- `python3 -m pi_controller.main`

Controls:

- Wind strength (fan): `q` up, `a` down
- Color (hue): `w` up, `s` down
- Color intensity (light): `e` up, `d` down
- Touch pulse (snare trigger): `t` (independent of start/send)
- Start/send (button edge): `Enter` (or `space`)
- Reset all values to defaults: `z`

## Raspberry Pi camera deps

For `picamera2` on Raspberry Pi OS, install via apt:

- `sudo apt update`
- `sudo apt install -y python3-picamera2`

Then install Python package deps:

- `pip3 install -r requirements.txt`

For full GPIO/I2C support on Pi:

- `pip3 install -r requirements-pi.txt`

## Wiring

- See [pinout.md](/Users/serafima/Developer/botanicalBeats/docs/pinout.md) for full wiring map used by this project.
