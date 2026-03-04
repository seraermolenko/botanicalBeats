from dataclasses import dataclass


@dataclass(frozen=True)
class OscConfig:
    sonic_pi_host: str = "127.0.0.1"
    sonic_pi_port: int = 4560
    visual_host: str = "127.0.0.1"
    visual_port: int = 9001


@dataclass(frozen=True)
class TimingConfig:
    talking_seconds: float = 3.0
    listening_seconds: float = 10.0
    thanks_seconds: float = 3.0


@dataclass(frozen=True)
class RateConfig:
    idle_poll_hz: float = 30.0
    listening_param_hz: float = 30.0


@dataclass(frozen=True)
class HardwareConfig:
    # NOTE: Set to True on Raspberry Pi to enable GPIO/I2C hardware paths.\
    use_pi_hardware: bool = True

    # GPIO pin map
    fan_pwm_gpio: int = 12
    led_data_gpio: int = 18
    start_button_gpio: int = 23

    # I2C addresses
    ads1115_pots_addr: int = 0x48
    ads1115_plant_addr: int = 0x49
    tcs34725_addr: int = 0x29


OSC = OscConfig()
TIMING = TimingConfig()
RATES = RateConfig()
HARDWARE = HardwareConfig()
