"""ダッシュボードのWeb UIと揃えたブランド定義（配色・アイコン）。

app/static/css/tokens.cssの --color-gamelog-* トークンと同じ値を使う
（デスクトップアプリからCSSを読み込むことはできないため、ここに複製している）。
"""

from __future__ import annotations

from PIL import Image, ImageDraw

APP_NAME = "VRCダッシュボード連携ツール"

# app/static/css/tokens.css の --color-gamelog-* と揃えている。
COLOR_PRIMARY = "#8B5CF6"
COLOR_PRIMARY_HOVER = "#7C3AED"
COLOR_BG_SOFT = "#F5F3FF"
COLOR_BORDER = "#DDD6FE"
COLOR_TEXT = "#1F2937"
COLOR_TEXT_MUTED = "#6B7280"
COLOR_SURFACE = "#FFFFFF"
COLOR_DANGER = "#EF4444"

_PRIMARY_RGB = (139, 92, 246)


def build_icon_image(size: int = 64) -> Image.Image:
    """外部アセットを使わず、シンプルな円+"V"のアイコンをその場で生成する。"""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = size / 64
    margin = 2 * scale
    draw.ellipse((margin, margin, size - margin, size - margin), fill=(*_PRIMARY_RGB, 255))
    draw.line(
        (20 * scale, 22 * scale, 32 * scale, 44 * scale),
        fill=(255, 255, 255, 255),
        width=max(1, round(6 * scale)),
    )
    draw.line(
        (44 * scale, 22 * scale, 32 * scale, 44 * scale),
        fill=(255, 255, 255, 255),
        width=max(1, round(6 * scale)),
    )
    return image
