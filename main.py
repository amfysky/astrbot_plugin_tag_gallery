from pathlib import Path

from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.core import AstrBotConfig
from astrbot.core.platform import AstrMessageEvent
from astrbot.core.star.filter.event_message_type import EventMessageType
from astrbot.core.star.star_tools import StarTools

from .core import GalleryImageMerger, ImageStore
from .handle.auto import GalleryAuto
from .handle.operate import GalleryOperate


@register(
    "astrbot_plugin_gallery",
    "amfysky",
    "标签化表情包池：内容寻址去重、一图多标签、引用图/短hash 操作，注入 LLM 工具按语义发表情",
    "3.0.0",
)
class GalleryPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.conf = config

        # 数据目录沿用旧名 astrbot_plugin_gallery，避免改插件名后丢失已有图片
        self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_gallery")
        # 图片池与索引的根目录（可在配置里改）
        base = config.get("galleries_dir") or self.plugin_data_dir / "galleries"
        self.base_dir = Path(base).resolve()

    async def initialize(self):
        self.store = ImageStore(self.base_dir)
        await self.store.initialize()
        self.merger = GalleryImageMerger()
        self.operator = GalleryOperate(self.store, self.merger)
        self.auto = GalleryAuto(self.context, self.conf, self.store)

    # ============ 自动收集 ============

    @filter.event_message_type(EventMessageType.ALL)
    async def auto_collect_image(self, event: AstrMessageEvent):
        """自动收集群聊图片，用 LLM 打标签入池"""
        await self.auto.collect_image(event)

    # ============ 指令（pic 命令组，写操作需管理员）============

    @filter.command_group("pic", alias={"图库"})
    def pic(self):
        """表情包图库指令组，发 `pic help` 查看帮助"""

    @pic.command("help", alias={"帮助"})
    async def pic_help(self, event: AstrMessageEvent):
        await self.operator.help(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @pic.command("save", alias={"存图", "存", "添加"})
    async def pic_save(self, event: AstrMessageEvent):
        await self.operator.save(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @pic.command("tag", alias={"打标", "加标签"})
    async def pic_tag(self, event: AstrMessageEvent):
        await self.operator.tag(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @pic.command("untag", alias={"去标", "删标签"})
    async def pic_untag(self, event: AstrMessageEvent):
        await self.operator.untag(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @pic.command("delete", alias={"del", "删图", "删", "删除"})
    async def pic_delete(self, event: AstrMessageEvent):
        await self.operator.delete(event)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @pic.command("gc", alias={"清理"})
    async def pic_gc(self, event: AstrMessageEvent):
        await self.operator.gc(event)

    @pic.command("view", alias={"看图", "看", "查看"})
    async def pic_view(self, event: AstrMessageEvent):
        await self.operator.view(event)

    @pic.command("tags", alias={"标签", "标签列表"})
    async def pic_tags(self, event: AstrMessageEvent):
        await self.operator.tags(event)

    @pic.command("info", alias={"信息", "详情", "图片信息"})
    async def pic_info(self, event: AstrMessageEvent):
        await self.operator.info(event)

    @pic.command("search", alias={"搜图", "找图", "搜"})
    async def pic_search(self, event: AstrMessageEvent):
        await self.operator.search(event)

    # ============ LLM 函数工具（供大模型主动调用）============

    @filter.llm_tool(name="list_tags")
    async def list_tags(self, event: AstrMessageEvent):
        """列出所有可用的表情包标签及图片数量，用于了解可以发送哪些类型的表情。"""
        counts = self.store.all_tags()
        if not counts:
            return "当前没有任何表情包"
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return "可用标签：\n" + "\n".join(f"- {t}（{c} 张）" for t, c in ordered)

    @filter.llm_tool(name="send_image_by_tag")
    async def send_image_by_tag(self, event: AstrMessageEvent, tag: str):
        """从指定标签随机发送一张表情包图片给用户。当用表情包回应会更生动时调用。

        Args:
            tag(string): 标签名，须是 list_tags 返回的标签之一
        """
        h = self.store.random_by_tag(tag)
        if not h:
            return f"标签【{tag}】下没有图片，请先用 list_tags 查看可用标签"
        p = self.store.path_of(h)
        if not p:
            return f"标签【{tag}】的图片文件缺失"
        await event.send(event.image_result(str(p)))
        return f"已发送一张【{tag}】表情包"
