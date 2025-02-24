import time
import time
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import smbus
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306

# Initialize I2C bus using smbus
bus = smbus.SMBus(1)  # Use 1 for Raspberry Pi (or 0 for older versions)

# TCA9548A address
TCA9548A_ADDRESS = 0x70  # Address of the multiplexer

# OLED display addresses on the multiplexer
OLED1_CHANNEL = 2  # First OLED on channel 2
OLED2_CHANNEL = 3  # Second OLED on channel 3

# OLED display settings
WIDTH = 128
HEIGHT = 64
OLED_ADDRESS = 0x3C  # Common I2C address for SSD1306 OLED displays

def select_channel(channel):
    """Select the specified channel on the TCA9548A multiplexer"""
    if channel > 7:
        return
    bus.write_byte(TCA9548A_ADDRESS, 1 << channel)

def init_display(channel):
    """Initialize an OLED display on the specified channel"""
    select_channel(channel)
    # Create luma.oled device
    serial = i2c(port=1, address=OLED_ADDRESS)
    display = ssd1306(serial, width=WIDTH, height=HEIGHT)
    return display

# Initialize both OLED displays
try:
    oled1 = init_display(OLED1_CHANNEL)
    oled2 = init_display(OLED2_CHANNEL)
    print("Both displays initialized successfully")
except Exception as e:
    print(f"Error initializing displays: {e}")

# Try to load a font (use a more common font path)
try:
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 24)
    small_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
except OSError:
    # Fallback to default font if the specified font is not available
    font = ImageFont.load_default()
    small_font = ImageFont.load_default()

# Draw on displays
def update_displays():
    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    current_date = now.strftime("%Y-%m-%d")

    # Draw time on first display
    select_channel(OLED1_CHANNEL)
    with canvas(oled1) as draw:
        draw.text((10, 10), "TIME", font=small_font, fill="white")
        draw.text((10, 30), current_time, font=font, fill="white")

    # Draw date on second display
    select_channel(OLED2_CHANNEL)
    with canvas(oled2) as draw:
        draw.text((10, 10), "DATE", font=small_font, fill="white")
        draw.text((10, 30), current_date, font=font, fill="white")

# Main loop
try:
    print("Starting main loop. Press CTRL+C to exit.")
    while True:
        update_displays()
        time.sleep(1)  # Update every second
except KeyboardInterrupt:
    # Clear displays on exit
    select_channel(OLED1_CHANNEL)
    oled1.clear()

    select_channel(OLED2_CHANNEL)
    oled2.clear()
    print("Program ended by user")
except Exception as e:
    print(f"Error in main loop: {e}")
