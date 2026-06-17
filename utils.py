import re

import aiohttp

from astrbot import logger
from astrbot.core.message.components import Image, Reply
from astrbot.core.platform.astr_message_event import AstrMessageEvent


async def download_file(url: str) -> bytes | None:
    """下载图片"""
    url = url.replace("https://", "http://")
    try:
        async with aiohttp.ClientSession() as client:
            response = await client.get(url)
            return await response.read()
    except Exception as e:
        logger.error(f"图片下载失败: {e}")
        return None


async def get_image(
    event: AstrMessageEvent, reply: bool = True, get_url: bool = False
) -> bytes | str | None:
    """获取消息（或引用消息）里的图片，返回 bytes 或 url"""
    chain = event.get_messages()
    # 优先引用消息里的图
    if reply:
        reply_seg = next((seg for seg in chain if isinstance(seg, Reply)), None)
        if reply_seg and reply_seg.chain:
            for seg in reply_seg.chain:
                if isinstance(seg, Image) and (img_url := seg.url):
                    if get_url:
                        return img_url
                    if msg_image := await download_file(img_url):
                        return msg_image
    # 再看原始消息
    for seg in chain:
        if isinstance(seg, Image) and (img_url := seg.url):
            if get_url:
                return img_url
            if msg_image := await download_file(img_url):
                return msg_image
    return None


def filter_text(text: str, max_length: int = 128) -> str:
    """只保留中文/数字/字母，并截短"""
    f_str = re.sub(r"[^一-龥a-zA-Z0-9]", "", text)
    return f_str if f_str.isdigit() else f_str[:max_length]
