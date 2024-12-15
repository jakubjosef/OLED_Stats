import time
import board
import busio
import gpiozero
from PIL import Image, ImageDraw, ImageFont
import adafruit_ssd1306
import subprocess
import requests
from typing import Tuple, Dict
import logging

class OLEDStatsDisplay:
    # Display constants
    WIDTH = 128
    HEIGHT = 64
    BORDER = 5
    REFRESH_RATE = 60.0  # seconds - increased to avoid API rate limits
    I2C_ADDRESS = 0x3C
    RESET_PIN = 4
    PRICE_FONT_SIZE = 32  # Increased from 24 to 32
    LABEL_FONT_SIZE = 14  # Slightly larger label font

    def __init__(self):
        # Configure logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

        # Initialize display hardware
        self._setup_display()

        # Initialize drawing resources
        self.image = Image.new("1", (self.WIDTH, self.HEIGHT))
        self.draw = ImageDraw.Draw(self.image)
        try:
            self.price_font = ImageFont.truetype('PixelOperator.ttf', self.PRICE_FONT_SIZE)
            self.label_font = ImageFont.truetype('PixelOperator.ttf', self.LABEL_FONT_SIZE)
        except OSError:
            self.logger.warning("PixelOperator font not found, falling back to default")
            self.price_font = ImageFont.load_default()
            self.label_font = ImageFont.load_default()

    def _setup_display(self):
        """Initialize the OLED display with proper reset sequence."""
        try:
            # Setup reset pin
            self.reset_pin = gpiozero.OutputDevice(self.RESET_PIN, active_high=False)

            # Perform reset sequence
            self._reset_display()

            # Initialize I2C and display
            i2c = board.I2C()
            self.oled = adafruit_ssd1306.SSD1306_I2C(
                self.WIDTH, self.HEIGHT, i2c, addr=self.I2C_ADDRESS
            )

            # Clear display
            self.clear_display()

        except Exception as e:
            self.logger.error(f"Failed to initialize display: {str(e)}")
            raise

    def _reset_display(self):
        """Perform hardware reset sequence."""
        self.reset_pin.on()
        time.sleep(0.1)
        self.reset_pin.off()
        time.sleep(0.1)
        self.reset_pin.on()

    def clear_display(self):
        """Clear the display buffer and update."""
        self.oled.fill(0)
        self.oled.show()

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

    def _get_temperature(self) -> str:
        """Get system temperature."""
        try:
            cmd = "vcgencmd measure_temp |cut -f 2 -d '='"
            return subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
        except subprocess.SubprocessError as e:
            self.logger.error(f"Failed to get temperature: {str(e)}")
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
        """Update the display with Bitcoin price and temperature."""
        # Clear the image
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), outline=0, fill=0)

        # Get current price and temperature
        btc_price = self._get_bitcoin_price()
        temp = self._get_temperature()

        # Draw Bitcoin price centered and large
        price_x, price_y = self._center_text(btc_price, self.price_font, -8)
        self.draw.text((price_x, price_y), btc_price, font=self.price_font, fill=255)

        # Draw "BTC/USD" label below price
        label = "BTC/USD"
        label_x, label_y = self._center_text(label, self.label_font, 20)
        self.draw.text((label_x, label_y), label, font=self.label_font, fill=255)

        # Draw temperature at bottom right
        temp_x = self.WIDTH - self._get_text_dimensions(temp, self.label_font)[0] - 2
        self.draw.text((temp_x, self.HEIGHT - 14), temp, font=self.label_font, fill=255)

        # Update display
        self.oled.image(self.image)
        self.oled.show()

    def run(self):
        """Main loop to continuously update the display."""
        self.logger.info("Starting OLED display with Bitcoin price")
        try:
            while True:
                self.update_display()
                time.sleep(self.REFRESH_RATE)
        except KeyboardInterrupt:
            self.logger.info("Shutting down display")
            self.clear_display()
        except Exception as e:
            self.logger.error(f"Unexpected error: {str(e)}")
            self.clear_display()

if __name__ == "__main__":
    try:
        display = OLEDStatsDisplay()
        display.run()
    except Exception as e:
        logging.error(f"Failed to start display: {str(e)}")
