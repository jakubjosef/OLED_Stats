import time
from datetime import datetime
import logging
import requests
from PIL import Image, ImageDraw, ImageFont
from smbus2 import SMBus
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106

class MultiDisplaySystem:
    # Display constants
    WIDTH = 128
    HEIGHT = 64
    REFRESH_RATE_SLOW = 300  # 5 minutes in seconds
    REFRESH_RATE_FAST = 1    # 1 second for clock
    I2C_PORT = 1             # I2C port number
    OLED_I2C_ADDRESS = 0x3C  # Common OLED address

    # I2C Settings
    TCA9548A_ADDRESS = 0x70  # TCA9548A multiplexer address
    BTC_DISPLAY_CHANNEL = 2  # First display channel
    CLOCK_DISPLAY_CHANNEL = 3  # Second display channel
    TEMP_DISPLAY_CHANNEL = 4  # Third display channel

    # Sensor Settings
    SI7021_ADDRESS = 0x40    # Si7021 temperature/humidity sensor

    # Si7021 commands
    MEASURE_HUMIDITY = 0xF5
    MEASURE_TEMPERATURE = 0xF3
    READ_TEMP_FROM_PREVIOUS_RH = 0xE0

    def __init__(self):
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

        # Initialize I2C bus
        self.bus = SMBus(self.I2C_PORT)

        # Reset multiplexer to make sure we start clean
        try:
            self.bus.write_byte(self.TCA9548A_ADDRESS, 0)
            self.logger.info(f"Reset TCA9548A multiplexer at address 0x{self.TCA9548A_ADDRESS:02X}")
        except Exception as e:
            self.logger.error(f"Failed to reset multiplexer: {e}")

        # Initialize displays
        self.displays = {}
        self._setup_displays()

        # Data storage
        self.btc_price = "Loading..."
        self.outside_temp = None
        self.outside_humidity = None
        self.inside_temp = None
        self.inside_humidity = None
        self.last_slow_update = 0

        # Initialize fonts
        try:
            self.large_font = ImageFont.truetype('PixelOperator.ttf', 32)
            self.medium_font = ImageFont.truetype('PixelOperator.ttf', 20)
            self.small_font = ImageFont.truetype('PixelOperator.ttf', 14)
        except OSError:
            self.logger.warning("PixelOperator font not found, falling back to default")
            # Use proportional sizes with default font
            self.large_font = ImageFont.load_default()
            self.medium_font = ImageFont.load_default()
            self.small_font = ImageFont.load_default()

    def select_channel(self, channel):
        """Select the specified channel on TCA9548A multiplexer"""
        if channel > 7:
            return
        try:
            self.bus.write_byte(self.TCA9548A_ADDRESS, 1 << channel)
            time.sleep(0.1)  # Give it a moment to switch
        except Exception as e:
            self.logger.error(f"Failed to select channel {channel}: {e}")

    def _setup_displays(self):
        """Initialize all three OLED displays"""
        display_channels = [
            ('btc', self.BTC_DISPLAY_CHANNEL),
            ('clock', self.CLOCK_DISPLAY_CHANNEL),
            ('temp', self.TEMP_DISPLAY_CHANNEL)
        ]

        for name, channel in display_channels:
            try:
                # First reset the channel
                self.select_channel(channel)
                time.sleep(0.1)

                # Scan for devices on this channel
                try:
                    detected = False
                    for addr in range(0x3C, 0x3E):  # Common OLED addresses are 0x3C and 0x3D
                        try:
                            self.bus.read_byte(addr)
                            self.logger.info(f"Device detected at address 0x{addr:02X} on channel {channel}")
                            detected = True
                            # If device found at address other than expected, update the address
                            if addr != self.OLED_I2C_ADDRESS:
                                self.logger.info(f"Using detected address 0x{addr:02X} instead of default 0x{self.OLED_I2C_ADDRESS:02X}")
                                serial = i2c(port=self.I2C_PORT, address=addr)
                            else:
                                serial = i2c(port=self.I2C_PORT, address=self.OLED_I2C_ADDRESS)
                            break
                        except:
                            pass

                    if not detected:
                        self.logger.warning(f"No display detected on channel {channel}, using default address")
                        serial = i2c(port=self.I2C_PORT, address=self.OLED_I2C_ADDRESS)
                except Exception as e:
                    self.logger.error(f"Error scanning channel {channel}: {e}")
                    serial = i2c(port=self.I2C_PORT, address=self.OLED_I2C_ADDRESS)

                # Initialize display with detected or default address
                self.displays[name] = sh1106(serial, rotate=0)
                self.logger.info(f"{name.upper()} display initialized on channel {channel}")

                # Quick display test
                with canvas(self.displays[name]) as draw:
                    draw.text((10, 20), f"INIT {name.upper()}", fill="white")
                time.sleep(0.5)

            except Exception as e:
                self.logger.error(f"Failed to initialize {name} display on channel {channel}: {e}")
                # Continue trying to initialize other displays

    def _read_si7021(self):
        """Read temperature and humidity from Si7021 sensor"""
        try:
            # The Si7021 is likely on the main I2C bus, not through the multiplexer
            # Reset the multiplexer to none selected to access the main I2C bus
            self.bus.write_byte(self.TCA9548A_ADDRESS, 0)
            time.sleep(0.1)  # Give it time to reset

            # First read humidity - No Hold Master Mode
            self.bus.write_byte(self.SI7021_ADDRESS, self.MEASURE_HUMIDITY)
            time.sleep(0.03)  # Wait for measurement to complete

            # Read the raw humidity data (need to read from the device after commanding measurement)
            try:
                data = self.bus.read_i2c_block_data(self.SI7021_ADDRESS, 0, 3)  # Read 3 bytes including CRC
                raw_humidity = (data[0] << 8) + data[1]
                humidity = ((125.0 * raw_humidity) / 65536.0) - 6
                self.logger.debug(f"Raw humidity data: {data[0]:02x} {data[1]:02x}, value: {raw_humidity}")
            except Exception as e:
                self.logger.error(f"Failed to read humidity: {e}")
                humidity = None

            # Now read temperature
            self.bus.write_byte(self.SI7021_ADDRESS, self.MEASURE_TEMPERATURE)
            time.sleep(0.03)  # Wait for measurement to complete

            # Read the raw temperature data
            try:
                data = self.bus.read_i2c_block_data(self.SI7021_ADDRESS, 0, 3)  # Read 3 bytes including CRC
                raw_temp = (data[0] << 8) + data[1]
                temp = ((175.72 * raw_temp) / 65536.0) - 46.85
                self.logger.debug(f"Raw temp data: {data[0]:02x} {data[1]:02x}, value: {raw_temp}")
            except Exception as e:
                self.logger.error(f"Failed to read temperature: {e}")
                temp = None

            # Format the results
            if temp is not None:
                temp = round(temp, 1)
            if humidity is not None:
                humidity = round(humidity, 1)

            return temp, humidity

        except Exception as e:
            self.logger.error(f"Failed to read Si7021: {e}")
            return None, None

    def _get_bitcoin_price(self):
        """Get current Bitcoin price from CoinGecko API"""
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
            self.logger.error(f"Failed to get Bitcoin price: {e}")
            return "Error"

    def _get_outside_weather(self):
        """Get outside temperature and humidity for Prague using WeatherAPI.com"""
        try:
            # Using WeatherAPI.com - free tier with no API key required for basic requests
            url = "https://weatherapi-com.p.rapidapi.com/current.json"

            querystring = {"q": "Prague"}

            headers = {
                "X-RapidAPI-Key": "SIGN_UP_FOR_KEY",  # Replace with your RapidAPI key
                "X-RapidAPI-Host": "weatherapi-com.p.rapidapi.com"
            }

            # Fallback to Open-Meteo (completely free, no API key)
            if headers["X-RapidAPI-Key"] == "SIGN_UP_FOR_KEY":
                self.logger.info("Using Open-Meteo API as fallback")
                # Prague coordinates: latitude 50.08, longitude 14.42
                url = "https://api.open-meteo.com/v1/forecast"
                params = {
                    "latitude": 50.08,
                    "longitude": 14.42,
                    "current": "temperature_2m,relative_humidity_2m",
                    "timezone": "Europe/Prague"
                }

                response = requests.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                temp = data["current"]["temperature_2m"]
                humidity = data["current"]["relative_humidity_2m"]
            else:
                # Use RapidAPI WeatherAPI if key is provided
                response = requests.get(url, headers=headers, params=querystring)
                response.raise_for_status()
                data = response.json()

                temp = data["current"]["temp_c"]
                humidity = data["current"]["humidity"]

            return round(temp, 1), humidity
        except Exception as e:
            self.logger.error(f"Failed to get outside weather: {e}")
            return None, None

    def _update_data(self):
        """Update all slow-refreshing data (every 5 minutes)"""
        current_time = time.time()
        if current_time - self.last_slow_update >= self.REFRESH_RATE_SLOW:
            self.logger.info("Updating slow-refresh data (BTC, temperatures)")

            # Update Bitcoin price
            try:
                btc_price = self._get_bitcoin_price()
                if btc_price != "Error":
                    self.btc_price = btc_price
                    self.logger.info(f"Updated BTC price: {self.btc_price}")
                else:
                    self.logger.warning("Failed to update BTC price")
            except Exception as e:
                self.logger.error(f"Error updating BTC price: {e}")

            # Update inside temperature data
            try:
                temp, humidity = self._read_si7021()
                if temp is not None and humidity is not None:
                    self.inside_temp, self.inside_humidity = temp, humidity
                    self.logger.info(f"Updated inside conditions: {self.inside_temp}°C, {self.inside_humidity}%")
                else:
                    self.logger.warning("Failed to read inside temperature/humidity")
            except Exception as e:
                self.logger.error(f"Error reading inside sensors: {e}")

            # Update outside temperature data
            try:
                temp, humidity = self._get_outside_weather()
                if temp is not None and humidity is not None:
                    self.outside_temp, self.outside_humidity = temp, humidity
                    self.logger.info(f"Updated outside conditions: {self.outside_temp}°C, {self.outside_humidity}%")
                else:
                    self.logger.warning("Failed to get outside weather data")
            except Exception as e:
                self.logger.error(f"Error getting outside weather: {e}")

            self.last_slow_update = current_time

    def _update_btc_display(self):
        """Update the Bitcoin price display"""
        if 'btc' not in self.displays:
            return

        self.select_channel(self.BTC_DISPLAY_CHANNEL)
        with canvas(self.displays['btc']) as draw:
            # Draw Bitcoin price in large font
            price_text = self.btc_price
            price_bbox = draw.textbbox((0, 0), price_text, font=self.large_font)
            price_width = price_bbox[2] - price_bbox[0]
            price_x = (self.WIDTH - price_width) // 2
            draw.text((price_x, 10), price_text, font=self.large_font, fill="white")

            # Draw BTC/USD label below price
            label = "BTC/USD"
            label_bbox = draw.textbbox((0, 0), label, font=self.small_font)
            label_width = label_bbox[2] - label_bbox[0]
            label_x = (self.WIDTH - label_width) // 2
            draw.text((label_x, 45), label, font=self.small_font, fill="white")

    def _update_clock_display(self):
        """Update the clock display"""
        if 'clock' not in self.displays:
            return

        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")
        date_str = now.strftime("%Y-%m-%d")
        weekday = now.strftime("%A")

        self.select_channel(self.CLOCK_DISPLAY_CHANNEL)
        with canvas(self.displays['clock']) as draw:
            # Draw time in large font
            time_bbox = draw.textbbox((0, 0), time_str, font=self.large_font)
            time_width = time_bbox[2] - time_bbox[0]
            time_x = (self.WIDTH - time_width) // 2
            draw.text((time_x, 5), time_str, font=self.large_font, fill="white")

            # Draw date below time
            date_bbox = draw.textbbox((0, 0), date_str, font=self.small_font)
            date_width = date_bbox[2] - date_bbox[0]
            date_x = (self.WIDTH - date_width) // 2
            draw.text((date_x, 40), date_str, font=self.small_font, fill="white")

            # Draw weekday below date
            weekday_bbox = draw.textbbox((0, 0), weekday, font=self.small_font)
            weekday_width = weekday_bbox[2] - weekday_bbox[0]
            weekday_x = (self.WIDTH - weekday_width) // 2
            draw.text((weekday_x, 52), weekday, font=self.small_font, fill="white")

    def _update_temp_display(self):
        """Update the temperature display"""
        if 'temp' not in self.displays:
            return

        self.select_channel(self.TEMP_DISPLAY_CHANNEL)
        with canvas(self.displays['temp']) as draw:
            # Draw inside header
            draw.text((5, 0), "Inside:", font=self.small_font, fill="white")

            # Draw inside temperature and humidity
            if self.inside_temp is not None and self.inside_humidity is not None:
                inside_text = f"{self.inside_temp}°C {self.inside_humidity}%"
                draw.text((5, 14), inside_text, font=self.medium_font, fill="white")
            else:
                draw.text((5, 14), "No data", font=self.medium_font, fill="white")

            # Draw outside header
            draw.text((5, 34), "Outside (Prague):", font=self.small_font, fill="white")

            # Draw outside temperature and humidity
            if self.outside_temp is not None and self.outside_humidity is not None:
                outside_text = f"{self.outside_temp}°C {self.outside_humidity}%"
                draw.text((5, 48), outside_text, font=self.medium_font, fill="white")
            else:
                draw.text((5, 48), "No data", font=self.medium_font, fill="white")

    def update_displays(self):
        """Update all displays with current data"""
        try:
            # Update slow-refreshing data if needed
            self._update_data()

            # Update individual displays
            self._update_btc_display()
            self._update_clock_display()
            self._update_temp_display()

        except Exception as e:
            self.logger.error(f"Error updating displays: {e}")

    def run(self):
        """Main loop to continuously update the displays"""
        self.logger.info("Starting multi-display system")
        try:
            # Initial updates
            self._update_data()

            while True:
                self.update_displays()
                time.sleep(self.REFRESH_RATE_FAST)  # Update every second for the clock

        except KeyboardInterrupt:
            self.logger.info("Shutting down displays")
            for name, display in self.displays.items():
                try:
                    if name == 'btc':
                        self.select_channel(self.BTC_DISPLAY_CHANNEL)
                    elif name == 'clock':
                        self.select_channel(self.CLOCK_DISPLAY_CHANNEL)
                    elif name == 'temp':
                        self.select_channel(self.TEMP_DISPLAY_CHANNEL)
                    display.clear()
                except Exception as e:
                    self.logger.error(f"Error clearing {name} display: {e}")

        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            # Try to clear displays on error
            for name, display in self.displays.items():
                try:
                    if name == 'btc':
                        self.select_channel(self.BTC_DISPLAY_CHANNEL)
                    elif name == 'clock':
                        self.select_channel(self.CLOCK_DISPLAY_CHANNEL)
                    elif name == 'temp':
                        self.select_channel(self.TEMP_DISPLAY_CHANNEL)
                    display.clear()
                except:
                    pass

if __name__ == "__main__":
    try:
        system = MultiDisplaySystem()
        system.run()
    except Exception as e:
        logging.error(f"Failed to start multi-display system: {e}")
