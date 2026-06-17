import re

from astrbot.core.message.components import Image, Plain
from astrbot.core.platform import AstrMessageEvent

from ..core import GalleryImageMerger, ImageStore
from ..utils import filter_text, get_image

HEX = re.compile(r"^[0-9a-f]{4,64}$")

HELP = (
    "【pic 图库】(🔒=需管理员；下方 <短hash> 都可改成「引用那张图」)\n"
    "🔒 pic save <标签...>            带图/引用图，存图并打标签\n"
    "🔒 pic tag [短hash] <标签...>    给图追加标签\n"
    "🔒 pic untag [短hash] <标签...>  移除标签(清空则删图)\n"
    "🔒 pic delete [短hash...]        删除图片\n"
    "🔒 pic gc                        手动清理无用图片\n"
    "pic view <标签>                  查看该标签下所有图(拼图)\n"
    "pic view <短hash>                查看单张原图\n"
    "pic tags                        列出所有标签\n"
    "pic info [短hash]                查看某图的标签/创建者\n"
    "pic search <关键词>              语义检索(接入 embedding 后启用)"
)


class GalleryOperate:
    def __init__(self, store: ImageStore, merger: GalleryImageMerger):
        self.store = store
        self.merger = merger

        # (规范名, handler, 是否写操作, 中文别名...) —— 路由与管理员校验从一处生成
        spec = [
            ("save", self._save, True, "存图", "存", "添加"),
            ("tag", self._tag, True, "打标", "加标签", "标"),
            ("untag", self._untag, True, "去标", "删标签"),
            ("delete", self._delete, True, "del", "删图", "删", "删除"),
            ("gc", self._gc, True, "清理"),
            ("view", self._view, False, "看图", "看", "查看"),
            ("tags", self._tags, False, "标签", "标签列表"),
            ("info", self._info, False, "信息", "详情", "图片信息"),
            ("search", self._search, False, "搜图", "找图", "搜"),
        ]
        self._routes: dict = {}
        self._writes: set = set()
        for name, fn, is_write, *aliases in spec:
            for key in (name, *aliases):
                self._routes[key] = fn
                if is_write:
                    self._writes.add(key)

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

        if sub in self._writes and not event.is_admin():
            await event.send(event.plain_result("该操作需要管理员权限"))
            return

        handler = self._routes.get(sub)
        if not handler:
            await event.send(event.plain_result(f"未知子指令：{sub}\n\n{HELP}"))
            return
        await handler(event, rest)

    # ---------------- 工具 ----------------

    @staticmethod
    def _resolve_msg(prefix: str, status: str) -> str:
        return {
            "tooshort": "短hash 至少要 4 位",
            "none": f"找不到图片 [{prefix}]",
            "ambiguous": f"短hash [{prefix}] 有歧义，请多写几位",
        }[status]

    async def _target(
        self, event: AstrMessageEvent, rest: list[str]
    ) -> tuple[str | None, list[str], str]:
        """定位目标图片：优先引用/附带的图片（按内容查池），否则用首参短hash。

        返回 (完整hash, 剩余参数, 错误信息)。命中时错误信息为空串。
        """
        image = await get_image(event)
        if isinstance(image, bytes):
            h = self.store.find_by_content(image)
            if h:
                return h, rest, ""  # 引用了图：剩余参数全是标签
            return None, [], "这张图不在库里（可先 pic save 存入）"
        if rest:
            full, status = self.store.resolve(rest[0])
            if status == "ok":
                return full, rest[1:], ""
            return None, [], self._resolve_msg(rest[0], status)
        return None, [], "请引用要操作的图片，或给出短hash"

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
        """pic tag <短hash> <标签...>  或  (引用图) pic tag <标签...>"""
        full, extra, err = await self._target(event, rest)
        if not full:
            await event.send(event.plain_result(err))
            return
        tags = self._clean_tags(extra)
        if not tags:
            await event.send(event.plain_result("请指定要添加的标签"))
            return
        now = self.store.add_tags(full, tags)
        await event.send(
            event.plain_result(f"[{self.store.short(full)}] 现有标签：{'、'.join(now)}")
        )

    async def _untag(self, event: AstrMessageEvent, rest: list[str]):
        """pic untag <短hash> <标签...>  或  (引用图) pic untag <标签...>"""
        full, extra, err = await self._target(event, rest)
        if not full:
            await event.send(event.plain_result(err))
            return
        tags = self._clean_tags(extra)
        if not tags:
            await event.send(event.plain_result("请指定要移除的标签"))
            return
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
        """(引用图) pic delete  或  pic delete <短hash...>"""
        # 引用/附带图片 → 删这一张
        image = await get_image(event)
        if isinstance(image, bytes):
            h = self.store.find_by_content(image)
            if not h:
                await event.send(event.plain_result("这张图不在库里"))
                return
            self.store.delete(h)
            await event.send(event.plain_result(f"已删除 [{self.store.short(h)}]"))
            return
        # 否则按短hash 批量删
        if not rest:
            await event.send(
                event.plain_result("请引用要删的图片，或：pic delete <短hash...>")
            )
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
        """pic info <短hash>  或  (引用图) pic info"""
        full, _, err = await self._target(event, rest)
        if not full:
            await event.send(event.plain_result(err))
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
