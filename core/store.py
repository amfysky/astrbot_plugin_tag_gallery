import hashlib
import io
import json
import os
import random
from datetime import datetime
from pathlib import Path

from PIL import Image as PILImage

from astrbot.api import logger


class ImageStore:
    """内容寻址的图片池 + 标签索引。

    - 图片按 sha256 唯一存一份于 images/<前2位>/<sha256>.<ext>
    - index.json 记录 每张图 -> 多标签 + 元数据，是唯一真相源
    - 一图多义 = 一张图带多个标签；删到最后一个标签即回收该图
    """

    EXT = {"jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp"}
    SHORT_LEN = 7  # 展示用短 hash 长度
    MIN_PREFIX = 4  # 解析短 hash 的最小前缀长度

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.images_dir = self.base_dir / "images"
        self.index_path = self.base_dir / "index.json"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        # hash -> {ext, tags, creator_id, created_at, desc, embedding}
        self.images: dict[str, dict] = {}

    async def initialize(self):
        self._load()
        migrated = self._migrate_from_folders()
        removed = self._gc()
        if migrated:
            logger.info(f"[gallery] 已从旧图库迁移 {migrated} 张图片")
        if any(removed):
            logger.info(f"[gallery] GC：悬空项 {removed[0]}、孤儿文件 {removed[1]}")

    # ---------------- 持久化 ----------------

    def _load(self):
        if self.index_path.exists():
            try:
                data = json.loads(self.index_path.read_text(encoding="utf-8"))
                self.images = data.get("images", {})
            except Exception as e:
                logger.error(f"[gallery] 读取 index.json 失败：{e}")
                self.images = {}

    def _save(self):
        """原子写：写临时文件再 os.replace，避免写一半损坏"""
        payload = {"version": 2, "images": self.images}
        tmp = self.index_path.with_name(self.index_path.name + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.index_path)

    # ---------------- 基础工具 ----------------

    @staticmethod
    def _hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def _detect_ext(cls, data: bytes) -> str:
        try:
            with PILImage.open(io.BytesIO(data)) as img:
                fmt = (img.format or "png").lower()
                return fmt if fmt in cls.EXT else "png"
        except Exception:
            return "png"

    def _path_for(self, h: str, ext: str) -> Path:
        return self.images_dir / h[:2] / f"{h}.{ext}"

    def short(self, h: str) -> str:
        return h[: self.SHORT_LEN]

    def path_of(self, h: str) -> Path | None:
        meta = self.images.get(h)
        if not meta:
            return None
        p = self._path_for(h, meta["ext"])
        return p if p.exists() else None

    def resolve(self, prefix: str) -> tuple[str | None, str]:
        """短 hash 前缀 -> (完整hash, 状态)。状态: ok/none/ambiguous/tooshort"""
        prefix = prefix.strip().lower()
        if len(prefix) < self.MIN_PREFIX:
            return None, "tooshort"
        matches = [h for h in self.images if h.startswith(prefix)]
        if not matches:
            return None, "none"
        if len(matches) > 1:
            return None, "ambiguous"
        return matches[0], "ok"

    # ---------------- 核心操作 ----------------

    def add(self, data: bytes, tags: list[str], creator_id: str) -> tuple[str, bool]:
        """存图并打标签。返回 (短hash, 是否新图)。已存在则只合并标签。"""
        clean_tags = sorted({t for t in tags if t})
        h = self._hash(data)
        if h in self.images:
            merged = sorted(set(self.images[h]["tags"]) | set(clean_tags))
            self.images[h]["tags"] = merged
            self._save()
            return self.short(h), False

        ext = self._detect_ext(data)
        p = self._path_for(h, ext)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)  # 先落盘文件
        self.images[h] = {
            "ext": ext,
            "tags": clean_tags,
            "creator_id": str(creator_id),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "desc": "",
            "embedding": None,
        }
        self._save()  # 再写索引
        return self.short(h), True

    def delete(self, h: str) -> bool:
        """彻底删除图片（文件 + 索引项）"""
        meta = self.images.pop(h, None)
        if meta is None:
            return False
        p = self._path_for(h, meta["ext"])
        if p.exists():
            p.unlink()
        self._save()
        return True

    def add_tags(self, h: str, tags: list[str]) -> list[str]:
        """给图片追加标签，返回最新标签列表"""
        meta = self.images[h]
        meta["tags"] = sorted(set(meta["tags"]) | {t for t in tags if t})
        self._save()
        return meta["tags"]

    def remove_tags(self, h: str, tags: list[str]) -> tuple[list[str], bool]:
        """移除标签。返回 (剩余标签, 是否因清空而删除整张图)"""
        meta = self.images[h]
        meta["tags"] = [t for t in meta["tags"] if t not in set(tags)]
        if not meta["tags"]:
            self.delete(h)
            return [], True
        self._save()
        return meta["tags"], False

    # ---------------- 查询 ----------------

    def by_tag(self, tag: str) -> list[str]:
        return [h for h, m in self.images.items() if tag in m["tags"]]

    def all_tags(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for m in self.images.values():
            for t in m["tags"]:
                counts[t] = counts.get(t, 0) + 1
        return counts

    def random_by_tag(self, tag: str) -> str | None:
        hs = self.by_tag(tag)
        return random.choice(hs) if hs else None

    # ---------------- 回收（GC）----------------

    def _gc(self) -> tuple[int, int]:
        """启动自愈对账：删悬空项/空标签项、删孤儿文件。返回 (清理项数, 清理文件数)"""
        removed_entries = 0
        for h in list(self.images):
            m = self.images[h]
            p = self._path_for(h, m["ext"])
            if not m["tags"] or not p.exists():
                if p.exists():
                    p.unlink()
                del self.images[h]
                removed_entries += 1

        valid = {self._path_for(h, m["ext"]) for h, m in self.images.items()}
        removed_files = 0
        if self.images_dir.exists():
            for bucket in self.images_dir.iterdir():
                if not bucket.is_dir():
                    continue
                for f in bucket.iterdir():
                    if f.is_file() and f not in valid:
                        f.unlink()
                        removed_files += 1

        if removed_entries or removed_files:
            self._save()
        return removed_entries, removed_files

    def gc(self) -> tuple[int, int]:
        """供 /pic gc 手动触发"""
        return self._gc()

    # ---------------- 迁移 ----------------

    def _migrate_from_folders(self) -> int:
        """把旧的 galleries/<库名>/<图> 文件夹模型迁进图片池。

        - 每张图按内容哈希入池（跨文件夹同图自动合并成一份）
        - 标签 = 旧文件夹名（库名）
        - 只读不删旧文件夹；迁移过的库名记到 .migrated 防重复
        """
        marker = self.base_dir / ".migrated"
        done: set[str] = set()
        if marker.exists():
            done = set(marker.read_text(encoding="utf-8").split("\n"))

        migrated = 0
        newly_done: list[str] = []
        for folder in self.base_dir.iterdir():
            if not folder.is_dir() or folder == self.images_dir:
                continue
            if folder.name in done:
                continue
            for f in folder.iterdir():
                if not (f.is_file() and f.suffix.lower().lstrip(".") in self.EXT):
                    continue
                try:
                    data = f.read_bytes()
                except Exception:
                    continue
                # 旧文件名第3段是创建者ID，取不到就 unknown
                creator = "unknown"
                parts = f.stem.split("_")
                if len(parts) >= 3 and parts[2]:
                    creator = parts[2]
                _, is_new = self.add(data, [folder.name], creator)
                if is_new:
                    migrated += 1
            newly_done.append(folder.name)

        if newly_done:
            marker.write_text(
                "\n".join(sorted(done | set(newly_done))), encoding="utf-8"
            )
        return migrated
