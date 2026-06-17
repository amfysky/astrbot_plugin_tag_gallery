import re

from astrbot.core.message.components import Image, Plain
from astrbot.core.platform import AstrMessageEvent

from ..core import GalleryImageMerger, ImageStore
from ..utils import filter_text, get_image

HEX = re.compile(r"^[0-9a-f]{4,64}$")

HELP = (
    "【pic 图库】(🔒=需要管理员)\n"
    "🔒 pic save <标签...>        带图/引用图，存图并打标签\n"
    "🔒 pic tag <短hash> <标签...>   给图追加标签\n"
    "🔒 pic untag <短hash> <标签...> 移除标签(清空则删图)\n"
    "🔒 pic delete <短hash...>      彻底删除图片\n"
    "🔒 pic gc                    手动清理无用图片\n"
    "pic view <标签>              查看该标签下所有图(拼图)\n"
    "pic view <短hash>            查看单张原图\n"
    "pic tags                    列出所有标签\n"
    "pic info <短hash>            查看某图的标签/创建者\n"
    "pic search <关键词>          语义检索(接入 embedding 后启用)"
)


class GalleryOperate:
    WRITE_SUBS = {"save", "tag", "untag", "delete", "del", "gc"}

    def __init__(self, store: ImageStore, merger: GalleryImageMerger):
        self.store = store
        self.merger = merger

    # ---------------- 分发 ----------------

    @staticmethod
    def _tokens(event: AstrMessageEvent) -> list[str]:
        """从 Plain 段取参数（避开引用概要/[MSG_ID:] 污染），去掉 pic 指令词"""
        plain = "".join(
            seg.text for seg in event.get_messages() if isinstance(seg, Plain)
        )
        plain = re.sub(r"\[MSG_ID:[^\]]*\]", " ", plain)
        return plain.strip().split()[1:]

    async def dispatch(self, event: AstrMessageEvent):
        tokens = self._tokens(event)
        if not tokens:
            await event.send(event.plain_result(HELP))
            return
        sub, rest = tokens[0].lower(), tokens[1:]

        if sub in self.WRITE_SUBS and not event.is_admin():
            await event.send(event.plain_result("该操作需要管理员权限"))
            return

        handler = {
            "save": self._save,
            "tag": self._tag,
            "untag": self._untag,
            "delete": self._delete,
            "del": self._delete,
            "gc": self._gc,
            "view": self._view,
            "tags": self._tags,
            "info": self._info,
            "search": self._search,
        }.get(sub)
        if not handler:
            await event.send(event.plain_result(f"未知子指令：{sub}\n\n{HELP}"))
            return
        await handler(event, rest)

    # ---------------- 工具 ----------------

    async def _resolve(self, event: AstrMessageEvent, prefix: str) -> str | None:
        full, status = self.store.resolve(prefix)
        if status == "ok":
            return full
        msg = {
            "tooshort": "短hash 至少要 4 位",
            "none": f"找不到图片 [{prefix}]",
            "ambiguous": f"短hash [{prefix}] 有歧义，请多写几位",
        }[status]
        await event.send(event.plain_result(msg))
        return None

    @staticmethod
    def _clean_tags(raw: list[str]) -> list[str]:
        return [t for t in (filter_text(x) for x in raw) if t]

    # ---------------- 写操作 ----------------

    async def _save(self, event: AstrMessageEvent, rest: list[str]):
        tags = self._clean_tags(rest)
        if not tags:
            await event.send(event.plain_result("用法：pic save <标签...>（至少一个标签）"))
            return
        image = await get_image(event)
        if not isinstance(image, bytes):
            await event.send(event.plain_result("请在指令里附带图片，或引用一张图片"))
            return
        short, is_new = self.store.add(image, tags, event.get_sender_id())
        verb = "已存图" if is_new else "图片已存在，已合并标签"
        await event.send(
            event.plain_result(f"{verb} [{short}]，标签：{'、'.join(tags)}")
        )

    async def _tag(self, event: AstrMessageEvent, rest: list[str]):
        if len(rest) < 2:
            await event.send(event.plain_result("用法：pic tag <短hash> <标签...>"))
            return
        full = await self._resolve(event, rest[0])
        if not full:
            return
        tags = self._clean_tags(rest[1:])
        if not tags:
            await event.send(event.plain_result("请指定要添加的标签"))
            return
        now = self.store.add_tags(full, tags)
        await event.send(
            event.plain_result(f"[{self.store.short(full)}] 现有标签：{'、'.join(now)}")
        )

    async def _untag(self, event: AstrMessageEvent, rest: list[str]):
        if len(rest) < 2:
            await event.send(event.plain_result("用法：pic untag <短hash> <标签...>"))
            return
        full = await self._resolve(event, rest[0])
        if not full:
            return
        tags = self._clean_tags(rest[1:])
        remaining, deleted = self.store.remove_tags(full, tags)
        if deleted:
            await event.send(
                event.plain_result(f"[{self.store.short(full)}] 已无标签，图片已删除")
            )
        else:
            await event.send(
                event.plain_result(
                    f"[{self.store.short(full)}] 现有标签：{'、'.join(remaining) or '无'}"
                )
            )

    async def _delete(self, event: AstrMessageEvent, rest: list[str]):
        if not rest:
            await event.send(event.plain_result("用法：pic delete <短hash...>"))
            return
        done = []
        for prefix in rest:
            full, status = self.store.resolve(prefix)
            if status == "ok" and self.store.delete(full):
                done.append(self.store.short(full))
        await event.send(
            event.plain_result(f"已删除：{'、'.join(done) if done else '无'}")
        )

    async def _gc(self, event: AstrMessageEvent, rest: list[str]):
        entries, files = self.store.gc()
        await event.send(
            event.plain_result(f"清理完成：悬空项 {entries}、孤儿文件 {files}")
        )

    # ---------------- 读操作 ----------------

    async def _view(self, event: AstrMessageEvent, rest: list[str]):
        if not rest:
            await event.send(event.plain_result("用法：pic view <标签> 或 pic view <短hash>"))
            return
        arg = rest[0]
        # 纯 hex 且能唯一解析 → 看单张原图
        if HEX.match(arg.lower()):
            full, status = self.store.resolve(arg)
            if status == "ok":
                p = self.store.path_of(full)
                if p:
                    await event.send(event.image_result(str(p)))
                    return
        # 否则按标签拼图
        tag = filter_text(arg)
        items = [
            (str(p), self.store.short(h))
            for h in self.store.by_tag(tag)
            if (p := self.store.path_of(h))
        ]
        if not items:
            await event.send(event.plain_result(f"标签【{tag}】下没有图片"))
            return
        merged = self.merger.create_merged(items)
        if merged:
            await event.send(event.chain_result([Image.fromBytes(merged)]))

    async def _tags(self, event: AstrMessageEvent, rest: list[str]):
        counts = self.store.all_tags()
        if not counts:
            await event.send(event.plain_result("还没有任何标签"))
            return
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        body = "、".join(f"{t}({c})" for t, c in ordered)
        await event.send(event.plain_result(f"共 {len(counts)} 个标签：\n{body}"))

    async def _info(self, event: AstrMessageEvent, rest: list[str]):
        if not rest:
            await event.send(event.plain_result("用法：pic info <短hash>"))
            return
        full = await self._resolve(event, rest[0])
        if not full:
            return
        m = self.store.images[full]
        await event.send(
            event.plain_result(
                f"短hash：{self.store.short(full)}\n"
                f"标签：{'、'.join(m['tags'])}\n"
                f"创建者：{m['creator_id']}\n"
                f"时间：{m['created_at']}\n"
                f"格式：{m['ext']}"
            )
        )

    async def _search(self, event: AstrMessageEvent, rest: list[str]):
        await event.send(event.plain_result("语义检索待接入 embedding，敬请期待"))
