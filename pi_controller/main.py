import asyncio

from pi_controller.hardware import HardwareIO
from pi_controller.osc_io import OscBus
from pi_controller.sensors import SensorPipeline
from pi_controller.state_machine import Controller


async def _main() -> None:
    print("[controller] running, sera is cool...")
    hw = HardwareIO()
    sensors = SensorPipeline()
    controller = Controller(hw=hw, osc=OscBus(), sensors=sensors)
    try:
        await controller.run_forever()
    finally:
        hw.cleanup()
        sensors.cleanup()


if __name__ == "__main__":
    asyncio.run(_main())
