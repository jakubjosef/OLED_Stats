import time
import board
import busio
import adafruit_ssd1306
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# Initialize I2C bus
i2c = busio.I2C(board.SCL, board.SDA)

# TCA9548A address
TCA9548A_ADDRESS = 0x70  # Address of the multiplexer

# OLED display addresses on the multiplexer
OLED1_CHANNEL = 2  # First OLED on channel 2
OLED2_CHANNEL = 3  # Second OLED on channel 3

# OLED display settings
WIDTH = 128
HEIGHT = 64
BORDER = 5

def select_channel(channel):
    """Select the specified channel on the TCA9548A multiplexer"""
    if channel > 7:
        return
    i2c.writeto(TCA9548A_ADDRESS, bytes([1 << channel]))

def init_display(channel):
    """Initialize an OLED display on the specified channel"""
    select_channel(channel)
    display = adafruit_ssd1306.SSD1306_I2C(WIDTH, HEIGHT, i2c)
    display.fill(0)
    display.show()
    return display

# Initialize both OLED displays
oled1 = init_display(OLED1_CHANNEL)
oled2 = init_display(OLED2_CHANNEL)

# Create blank images for drawing
image1 = Image.new("1", (WIDTH, HEIGHT))
image2 = Image.new("1", (WIDTH, HEIGHT))

# Get drawing objects to draw on images
draw1 = ImageDraw.Draw(image1)
draw2 = ImageDraw.Draw(image2)

# Load a font
font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 24)
small_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)

# Draw on displays
def update_displays():
    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    current_date = now.strftime("%Y-%m-%d")

    # Clear the images
    draw1.rectangle((0, 0, WIDTH, HEIGHT), outline=0, fill=0)
    draw2.rectangle((0, 0, WIDTH, HEIGHT), outline=0, fill=0)

    # Draw time on first display
    draw1.text((10, 10), "TIME", font=small_font, fill=255)
    draw1.text((10, 30), current_time, font=font, fill=255)

    # Draw date on second display
    draw2.text((10, 10), "DATE", font=small_font, fill=255)
    draw2.text((10, 30), current_date, font=font, fill=255)

    # Display the images on the OLEDs
    select_channel(OLED1_CHANNEL)
    oled1.image(image1)
    oled1.show()

    select_channel(OLED2_CHANNEL)
    oled2.image(image2)
    oled2.show()

# Main loop
try:
    while True:
        update_displays()
        time.sleep(1)  # Update every second
except KeyboardInterrupt:
    # Clear displays on exit
    select_channel(OLED1_CHANNEL)
    oled1.fill(0)
    oled1.show()

    select_channel(OLED2_CHANNEL)
    oled2.fill(0)
    oled2.show()
    print("Program ended by user")
