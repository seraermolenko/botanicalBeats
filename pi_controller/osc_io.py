from pythonosc.udp_client import SimpleUDPClient

from .config import OSC


class OscBus:
    def __init__(self) -> None:
        self._sp = SimpleUDPClient(OSC.sonic_pi_host, OSC.sonic_pi_port)
        self._viz = SimpleUDPClient(OSC.visual_host, OSC.visual_port)

    def state(self, name: str) -> None:
        address = f"/state/{name}"
        self._sp.send_message(address, 1)
        self._viz.send_message(address, 1)

    def frozen(self, fan: float, hue: float, light: float) -> None:
        self._sp.send_message("/frozen/fan", fan)
        self._sp.send_message("/frozen/hue", hue)
        self._sp.send_message("/frozen/light", light)
        self._viz.send_message("/frozen/fan", fan)
        self._viz.send_message("/frozen/hue", hue)
        self._viz.send_message("/frozen/light", light)

    def sensor(self, motion: float, rgb: tuple[float, float, float]) -> None:
        r, g, b = rgb
        self._sp.send_message("/sensor/motion", motion)
        self._sp.send_message("/sensor/rgb", [r, g, b])

    def touch(self) -> None:
        self._sp.send_message("/sensor/touch", 1)
        # Direct visual fallback so touch always yields a burst even if Sonic Pi cue forwarding is delayed.
        self._viz.send_message("/cue/snare", [0, 0, 1.0])

    def params(self, energy: float, density: float, sparkle: float, hue: float) -> None:
        self._sp.send_message("/param/energy", energy)
        self._sp.send_message("/param/density", density)
        self._sp.send_message("/param/sparkle", sparkle)
        self._viz.send_message("/viz/mod/energy", energy)
        self._viz.send_message("/viz/mod/hue", hue)
