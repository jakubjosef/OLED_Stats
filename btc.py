import time
import board
import busio
import gpiozero
from PIL import Image, ImageDraw, ImageFont
import requests
from typing import Tuple, Dict
import logging
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106

class OLEDStatsDisplay:
    # Display constants
    WIDTH = 128
    HEIGHT = 64
    BORDER = 5
    REFRESH_RATE = 60.0  # seconds
    OLED_I2C_PORT = 1  # I2C port number
    OLED_I2C_ADDRESS = 0x3C
    SI7021_ADDRESS = 0x40
    LIGHT_I2C_ADDRESS = 0x23
    PRICE_FONT_SIZE = 32
    LABEL_FONT_SIZE = 14

    # Si7021 commands
    MEASURE_HUMIDITY = 0xF5
    MEASURE_TEMPERATURE = 0xF3
    READ_TEMP_FROM_PREVIOUS_RH = 0xE0

    # BH1750 commands
    LIGHT_POWER_DOWN = 0x00
    LIGHT_POWER_ON = 0x01
    LIGHT_RESET = 0x07
    LIGHT_CONTINUOUS_HIGH_RES = 0x10

    def __init__(self):
        # Configure logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

        # Initialize I2C bus
        self.i2c = board.I2C()

        # Initialize sensors
        self._setup_si7021_sensor()
        self._setup_light_sensor()

        # Initialize display hardware
        self._setup_display()

        # Initialize fonts
        try:
            self.price_font = ImageFont.truetype('PixelOperator.ttf', self.PRICE_FONT_SIZE)
            self.label_font = ImageFont.truetype('PixelOperator.ttf', self.LABEL_FONT_SIZE)
        except OSError:
            self.logger.warning("PixelOperator font not found, falling back to default")
            self.price_font = ImageFont.load_default()
            self.label_font = ImageFont.load_default()

    def _setup_display(self):
        """Initialize the SH1106 OLED display using luma.oled."""
        try:
            # Initialize I2C interface
            serial = i2c(port=self.OLED_I2C_PORT, address=self.OLED_I2C_ADDRESS)

            # Create the SH1106 device
            self.oled = sh1106(serial, rotate=0)
            self.oled.contrast(255)  # Max contrast

            self.logger.info("SH1106 display initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize display: {str(e)}")
            raise

    def _setup_si7021_sensor(self):
        """Initialize the Si7021 temperature and humidity sensor."""
        try:
            self.si7021 = busio.I2C(board.SCL, board.SDA)
            # Check if sensor is present
            while not self.si7021.try_lock():
                pass
            addresses = self.si7021.scan()
            self.si7021.unlock()
            if self.SI7021_ADDRESS not in addresses:
                raise RuntimeError(f"No I2C device found at address {hex(self.SI7021_ADDRESS)}")
            self.logger.info(f"Si7021 sensor found at {hex(self.SI7021_ADDRESS)}")
        except Exception as e:
            self.logger.error(f"Failed to initialize Si7021 sensor: {str(e)}")
            raise

    def _read_si7021(self) -> Tuple[float, float]:
        """Read temperature and humidity from Si7021 sensor."""
        try:
            while not self.si7021.try_lock():
                pass

            # Read humidity first (temperature can be read from this measurement)
            self.si7021.writeto(self.SI7021_ADDRESS, bytes([self.MEASURE_HUMIDITY]))
            time.sleep(0.03)  # Wait for measurement
            raw_rh = bytearray(3)
            self.si7021.readfrom_into(self.SI7021_ADDRESS, raw_rh)

            # Read temperature from the humidity measurement
            self.si7021.writeto(self.SI7021_ADDRESS, bytes([self.READ_TEMP_FROM_PREVIOUS_RH]))
            raw_temp = bytearray(2)
            self.si7021.readfrom_into(self.SI7021_ADDRESS, raw_temp)

            self.si7021.unlock()

            # Convert raw humidity
            humidity = ((raw_rh[0] << 8) | raw_rh[1])
            humidity = ((125 * humidity) / 65536) - 6

            # Convert raw temperature
            temp = ((raw_temp[0] << 8) | raw_temp[1])
            temp = ((175.72 * temp) / 65536) - 46.85

            return round(temp, 1), round(humidity, 1)

        except Exception as e:
            self.logger.error(f"Failed to read Si7021: {str(e)}")
            self.si7021.unlock()
            return None, None

    def _setup_light_sensor(self):
        """Initialize the BH1750 light sensor."""
        try:
            self.light_sensor = busio.I2C(board.SCL, board.SDA)
            # Check if sensor is present
            while not self.light_sensor.try_lock():
                pass
            addresses = self.light_sensor.scan()
            self.light_sensor.unlock()
            if self.LIGHT_I2C_ADDRESS not in addresses:
                raise RuntimeError(f"No I2C device found at address {hex(self.LIGHT_I2C_ADDRESS)}")

            # Initialize the sensor
            self._light_sensor_write(self.LIGHT_POWER_ON)  # Turn on
            self._light_sensor_write(self.LIGHT_RESET)     # Reset
            self._light_sensor_write(self.LIGHT_CONTINUOUS_HIGH_RES)  # Set mode
            time.sleep(0.2)  # Wait for first measurement

            self.logger.info(f"Light sensor found at {hex(self.LIGHT_I2C_ADDRESS)}")
        except Exception as e:
            self.logger.error(f"Failed to initialize light sensor: {str(e)}")
            raise

    def _light_sensor_write(self, command):
        """Write command to light sensor."""
        try:
            while not self.light_sensor.try_lock():
                pass
            self.light_sensor.writeto(self.LIGHT_I2C_ADDRESS, bytes([command]))
            self.light_sensor.unlock()
        except Exception as e:
            self.light_sensor.unlock()
            raise e

    def _read_light(self) -> float:
        """Read light intensity from BH1750 sensor."""
        try:
            while not self.light_sensor.try_lock():
                pass

            # Read 2 bytes of light data
            result = bytearray(2)
            self.light_sensor.readfrom_into(self.LIGHT_I2C_ADDRESS, result)
            self.light_sensor.unlock()

            # Convert the raw data to lux
            light_level = (result[0] << 8 | result[1]) / 1.2
            return round(light_level, 1)

        except Exception as e:
            self.logger.error(f"Failed to read light: {str(e)}")
            self.light_sensor.unlock()
            return None

    def _get_bitcoin_price(self) -> str:
        """Get current Bitcoin price from CoinGecko API."""
        try:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": "bitcoin",
                "vs_currencies": "usd"
            }
            response = requests.get(url, params=params)
            response.raise_for_status()
            price = response.json()["bitcoin"]["usd"]
            return f"${price:,.0f}"
        except Exception as e:
            self.logger.error(f"Failed to get Bitcoin price: {str(e)}")
            return "Error"

    def _get_text_dimensions(self, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
        """Get the width and height of a text string with given font."""
        bbox = self.draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        return text_width, text_height

    def _center_text(self, text: str, font: ImageFont.FreeTypeFont, y_offset: int = 0) -> Tuple[int, int]:
        """Calculate position to center text horizontally."""
        text_width, text_height = self._get_text_dimensions(text, font)
        x = (self.WIDTH - text_width) // 2
        y = y_offset + (self.HEIGHT - text_height) // 2
        return x, y

    def update_display(self):
        """Update the display with Bitcoin price and sensor data."""
        try:
            # Get current values
            btc_price = self._get_bitcoin_price()
            temp, humidity = self._read_si7021()
            light = self._read_light()

            # Use Luma's canvas context manager for drawing
            with canvas(self.oled) as draw:
                self.draw = draw  # Store draw object for _get_text_dimensions

                # Draw Bitcoin price at the top
                price_x, _ = self._center_text(btc_price, self.price_font)
                draw.text((price_x, 2), btc_price, font=self.price_font, fill="white")

                # Draw BTC/USD label below price
                label = "BTC/USD"
                label_x, _ = self._center_text(label, self.label_font)
                # Position it just below the price
                _, price_height = self._get_text_dimensions(btc_price, self.price_font)
                draw.text((label_x, 6 + price_height), label, font=self.label_font, fill="white")

                # Draw environment data at the bottom
                y_pos = self.HEIGHT - 14

                # Temperature (left)
                if temp is not None:
                    temp_text = f"{temp}°C"
                    draw.text((2, y_pos), temp_text, font=self.label_font, fill="white")

                # Humidity (center)
                if humidity is not None:
                    humid_text = f"{humidity}%"
                    humid_x = (self.WIDTH - self._get_text_dimensions(humid_text, self.label_font)[0]) // 2
                    draw.text((humid_x, y_pos), humid_text, font=self.label_font, fill="white")

                # Light (right)
                if light is not None:
                    light_text = f"{light:.0f}lx"
                    light_x = self.WIDTH - self._get_text_dimensions(light_text, self.label_font)[0] - 2
                    draw.text((light_x, y_pos), light_text, font=self.label_font, fill="white")

        except Exception as e:
            self.logger.error(f"Failed to update display: {str(e)}")

    def run(self):
        """Main loop to continuously update the display."""
        self.logger.info("Starting OLED display with sensors")
        try:
            while True:
                self.update_display()
                time.sleep(self.REFRESH_RATE)
        except KeyboardInterrupt:
            self.logger.info("Shutting down display")
            self.oled.clear()
            self.oled.hide()
        except Exception as e:
            self.logger.error(f"Unexpected error: {str(e)}")
            self.oled.clear()
            self.oled.hide()

if __name__ == "__main__":
    try:
        display = OLEDStatsDisplay()
        display.run()
    except Exception as e:
        logging.error(f"Failed to start display: {str(e)}")
