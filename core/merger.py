from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from astrbot.api import logger


class GalleryImageMerger:
    """把一组图片拼成一张预览图，每张图下方标注其短 hash"""

    def __init__(self, thumb_size=(128, 128)):
        self.font_path = Path(__file__).parent.parent / "zzgf_dianhei.otf"
        self.thumbnail_size = thumb_size

    def _process_image(self, img_path, label, font) -> Image.Image | None:
        try:
            img = Image.open(img_path)
            # GIF 取第一帧
            if img.format == "GIF":
                img.seek(0)
            # 转换为 RGB：透明图（P/RGBA/LA）直接 convert("RGB") 会把透明区域
            # 填成调色板默认色（常表现为发绿/发黑），需先合成到白底再转 RGB
            if img.mode in ("P", "RGBA", "LA"):
                img = img.convert("RGBA")
                bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
                img = Image.alpha_composite(bg, img).convert("RGB")
            else:
                img = img.convert("RGB")
            # 缩放（用 LANCZOS 提升清晰度）
            img = img.resize(self.thumbnail_size, Image.Resampling.LANCZOS)

            draw = ImageDraw.Draw(img)

            # 文本尺寸
            bbox = draw.textbbox((0, 0), label, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            text_x = (self.thumbnail_size[0] - text_w) // 2
            text_y = self.thumbnail_size[1] - text_h - 1

            # 圆形背景
            radius = max(text_w, text_h) // 2 + 1

            circle_x1 = text_x - radius // 2
            circle_y1 = text_y
            circle_x2 = text_x + text_w + radius // 2
            circle_y2 = text_y + text_h // 2 + radius * 2 + 5

            draw.ellipse(
                [(circle_x1, circle_y1), (circle_x2, circle_y2)], fill=(255, 255, 255)
            )

            # 短 hash 标签
            draw.text((text_x, text_y), label, font=font, fill=(0, 0, 0))

            return img

        except Exception as e:
            logger.error(f"加载图片 {img_path} 时出错：{e}")
            return None

    def create_merged(self, items: list[tuple[str, str]]) -> bytes | None:
        """items: [(图片路径, 短hash标签), ...]，按给定顺序拼图"""
        thumb_w, thumb_h = self.thumbnail_size

        if not items:
            logger.warning("没有可拼接的图片")
            return None

        total = len(items)
        images_per_row = 5 if total <= 40 else 10
        width = thumb_w * (total if total <= 5 else images_per_row)
        height = thumb_h * ((total + images_per_row - 1) // images_per_row)

        merged = Image.new("RGB", (width, height), (255, 255, 255))
        font = ImageFont.truetype(self.font_path, 15)

        for idx, (img_path, label) in enumerate(items):
            img = self._process_image(img_path, label, font)
            if img:
                x = (idx % images_per_row) * thumb_w
                y = (idx // images_per_row) * thumb_h
                merged.paste(img, (x, y))

        out = BytesIO()
        merged.save(out, format="JPEG", quality=95)
        return out.getvalue()
