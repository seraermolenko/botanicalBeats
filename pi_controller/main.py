import asyncio

from pi_controller.hardware import HardwareIO
from pi_controller.keyboard_input import cleanup_keyboard_input
from pi_controller.osc_io import OscBus
from pi_controller.sensors import SensorPipeline
from pi_controller.state_machine import Controller


async def _main() -> None:
    print("[controller] running, sera is cool...")
    hw = HardwareIO()
    sensors = SensorPipeline(hw=hw)
    controller = Controller(hw=hw, osc=OscBus(), sensors=sensors)
    try:
        await controller.run_forever()
    finally:
        hw.cleanup()
        sensors.cleanup()
        cleanup_keyboard_input()


if __name__ == "__main__":
    asyncio.run(_main())
