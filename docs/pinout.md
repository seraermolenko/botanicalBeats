# Pinout (Raspberry Pi)

## Fan (4-pin)

- `12V` -> PSU `12V`
- `GND` -> PSU `GND` + Pi `GND` (common ground)
- `PWM` -> `GPIO12`
- `Tachometer` -> not used

## RGB LED Strip (3-pin)

- `5V` -> PSU `5V`
- `GND` -> PSU `GND` + Pi `GND` (common ground)
- `Data` -> `GPIO18`

## ADS1115 #1 (Potentiometers)

- `VDD` -> Pi `3.3V`
- `GND` -> Pi `GND`
- `SDA` -> `GPIO2`
- `SCL` -> `GPIO3`
- `ADDR` -> `GND` (`0x48`)
- `A0` -> Pot 1 wiper (fan)
- `A1` -> Pot 2 wiper (rgb/hue)
- `A2` -> Pot 3 wiper (light intensity)

## ADS1115 #2 (Plant Sensor)

- `VDD` -> Pi `3.3V`
- `GND` -> Pi `GND`
- `SDA` -> `GPIO2`
- `SCL` -> `GPIO3`
- `ADDR` -> `VDD` (`0x49`)
- `A0` -> Plant probe (petal)
- `A1` -> Soil reference probe

## TCS34725 (RGB + light sensor)

- `VIN` -> Pi `3.3V`
- `GND` -> Pi `GND`
- `SDA` -> `GPIO2`
- `SCL` -> `GPIO3`
- `LED` -> `GND` (off)

## GPIO Summary

- `GPIO2` -> I2C SDA
- `GPIO3` -> I2C SCL
- `GPIO12` -> Fan PWM
- `GPIO18` -> LED data
- `GPIO23` -> Start button (default in code, change if needed)

## Software mapping

See `pi_controller/config.py` (`HardwareConfig`) for the active pin/address map.
