import json
import re
import time

from astrbot.api import logger
from astrbot.core import AstrBotConfig
from astrbot.core.platform import AstrMessageEvent
from astrbot.core.provider.provider import Provider
from astrbot.core.star.context import Context

from ..core import ImageStore
from ..utils import download_file, get_image


class GalleryAuto:
    def __init__(self, context: Context, config: AstrBotConfig, store: ImageStore):
        self.context = context
        self.conf = config
        self.store = store
        self.last_collect_time: int = 0

    async def _get_llm_tags(self, image_url: str, known_tags: list[str]) -> list[str]:
        """调用 LLM 给图片打标签（可多义，返回标签列表）"""
        provider = (
            self.context.get_provider_by_id(self.conf["auto_collect"]["provider_id"])
            or self.context.get_using_provider()
        )
        if not isinstance(provider, Provider):
            return []

        system_prompt = (
            "你是表情包打标助手。给定一张图片，输出它的标签（含义/情绪/场景），"
            "一张图可有多个标签。\n"
            f"已有标签可复用：{known_tags}\n"
            '只输出 JSON：{"tags": ["标签1", "标签2"]}，不要任何多余文本。'
        )
        try:
            resp = await provider.text_chat(
                system_prompt=system_prompt,
                prompt="给这张图片打标签",
                image_urls=[image_url],
            )
            return self._parse_tags(resp.completion_text)
        except Exception as e:
            logger.error(f"LLM 打标失败：{e}")
            return []

    @staticmethod
    def _parse_tags(text: str) -> list[str]:
        if not text:
            return []
        match = re.search(r"\{[\s\S]*?\}", text)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict) and isinstance(data.get("tags"), list):
                return [str(t) for t in data["tags"] if str(t).strip()]
        except Exception:
            logger.warning(f"无法解析 LLM 标签输出：{text!r}")
        return []

    async def collect_image(self, event: AstrMessageEvent):
        """自动收集、打标图片"""
        conf = self.conf["auto_collect"]
        if not conf["enable_collect"]:
            return
        # 跳过插件自己的指令/唤醒消息，避免抓取指令里附带的图
        if event.is_at_or_wake_command:
            return
        if conf["whitelist"] and event.get_group_id() not in conf["whitelist"]:
            return
        if (
            conf["collect_cd"] > 0
            and int(time.time()) - self.last_collect_time < conf["collect_cd"]
        ):
            return

        image_url = await get_image(event, reply=False, get_url=True)
        if not isinstance(image_url, str):
            return
        self.last_collect_time = int(time.time())

        tags = await self._get_llm_tags(image_url, list(self.store.all_tags()))
        if not tags:
            return
        if image_bytes := await download_file(image_url):
            short, is_new = self.store.add(image_bytes, tags, event.get_sender_id())
            if is_new:
                logger.info(f"自动收集图片 [{short}]，标签：{tags}")
