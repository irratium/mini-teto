"""Builds windows/mini-teto.ico from sprites/idle.png (pixel art: nearest-neighbour scaling)."""
import os
import sys

from PIL import Image

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = Image.open(os.path.join(root, "sprites", "idle.png")).convert("RGBA")
side = max(src.size)
canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
canvas.paste(src, ((side - src.width) // 2, (side - src.height) // 2))
big = canvas.resize((256, 256), Image.NEAREST)
out = os.path.join(root, "windows", "mini-teto.ico")
big.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", out)
sys.exit(0)
