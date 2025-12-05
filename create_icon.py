"""Create icon for Sony Automator Controls."""
from PIL import Image, ImageDraw, ImageFont

# Create a 256x256 image with transparent background
size = 256
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Draw background circle - Elliott's teal color
bg_color = (0, 188, 212, 255)  # #00bcd4
draw.ellipse([20, 20, size-20, size-20], fill=bg_color)

# Draw "SAC" text in white
text_color = (255, 255, 255, 255)
try:
    font = ImageFont.truetype("arial.ttf", 80)
except:
    font = ImageFont.load_default()

text = "SAC"
bbox = draw.textbbox((0, 0), text, font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]
position = ((size - text_width) // 2, (size - text_height) // 2 - 10)
draw.text(position, text, fill=text_color, font=font)

# Save as ICO
img.save('static/sac_icon.ico', format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("Icon created: static/sac_icon.ico")
