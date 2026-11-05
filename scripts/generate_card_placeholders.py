"""One-off: render placeholder card art (no real logos) for every card in seed/cards.json.

Run from the repo root: `uv run python scripts/generate_card_placeholders.py`.
Official art can later replace these through the image upload endpoint.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SIZE = (856, 540)  # credit-card ratio (85.6 x 54 mm)
OUT_WIDTH = 800  # stored images are at most 800 px wide
NETWORK_WORDMARK = {"visa": "VISA", "mastercard": "Mastercard", "rupay": "RuPay"}
# (top-left, bottom-right) gradient colours per bank; all dark enough for white text.
GRADIENTS = {
    "HDFC": ((10, 40, 90), (4, 14, 40)),
    "ICICI": ((150, 50, 20), (50, 14, 10)),
    "SBI": ((20, 90, 140), (8, 30, 60)),
    "Axis": ((40, 90, 80), (10, 30, 30)),
    "Slice": ((70, 40, 130), (24, 12, 50)),
    "IDFC First": ((120, 20, 50), (40, 8, 24)),
    "BOB": ((190, 80, 20), (70, 24, 8)),
}
FONT_CANDIDATES = ["/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def gradient(top_left: tuple[int, ...], bottom_right: tuple[int, ...]) -> Image.Image:
    """Diagonal two-colour gradient."""
    w, h = SIZE
    img = Image.new("RGB", SIZE)
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / w + y / h) / 2
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(top_left, bottom_right))
    return img


def render(card: dict) -> Image.Image:
    img = gradient(*GRADIENTS[card["bank"]])
    draw = ImageDraw.Draw(img)
    white = (255, 255, 255)
    draw.text((48, 48), card["bank"].upper(), font=font(44), fill=white)
    draw.text((48, 110), card["name"], font=font(36), fill=(225, 225, 235))
    draw.rounded_rectangle((48, 250, 140, 320), radius=10, outline=(220, 200, 140), width=3)  # chip outline
    draw.text((48, 440), "PLACEHOLDER", font=font(20), fill=(170, 170, 185))
    wordmark = NETWORK_WORDMARK[card["network"]]
    draw.text((SIZE[0] - 48, SIZE[1] - 48), wordmark, font=font(48), fill=white, anchor="rb")
    return img


def main() -> None:
    cards = json.loads((ROOT / "seed" / "cards.json").read_text())
    out = ROOT / "seed" / "images"
    out.mkdir(exist_ok=True)
    for card in cards:
        art = render(card)
        art = art.resize((OUT_WIDTH, round(SIZE[1] * OUT_WIDTH / SIZE[0])), Image.LANCZOS)
        art.save(out / card["image"], "WEBP", quality=85)
        print("wrote", card["image"])


if __name__ == "__main__":
    main()
