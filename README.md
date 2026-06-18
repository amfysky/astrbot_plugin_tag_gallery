<div align="center">

# astrbot_plugin_gallery

_✨ [AstrBot](https://github.com/AstrBotDevs/AstrBot) 标签表情包池 ✨_

[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![GitHub](https://img.shields.io/badge/作者-amfysky-blue)](https://github.com/amfysky)

</div>

## 🤝 介绍

标签化的表情包 / 图片池。核心是把**存储**和**分类**拆开：

- **内容寻址、自动去重**：每张图按 `sha256` 只存一份，重复图自动合并。
- **一图多标签（多义）**：一张"笑哭"可同时属于 `开心`、`搞笑`，磁盘上只有一份。
- **引用图 / 短 hash 操作**：删图、改标签既能"引用那张图"，也能用 git 式短 hash。
- **注入 LLM 工具**：大模型能 `list_tags` 看有哪些标签、`send_image_by_tag` 按语义主动发表情（"开心≈高兴"由大模型自己理解）。
- **自动回收（GC）**：标签清空即删图，启动自愈对账清理孤儿文件，不留垃圾。

> 本插件 fork 并重写自 [Zhalslar/astrbot_plugin_gallery](https://github.com/Zhalslar/astrbot_plugin_gallery)，感谢原作者。

## 📦 安装

```bash
cd /AstrBot/data/plugins
git clone https://github.com/amfysky/astrbot_plugin_gallery
# 控制台重启 / 重载 AstrBot
```

旧版 `astrbot_plugin_gallery` 的图库文件夹放进图片池根目录，插件初始化时会**自动迁移**进池（文件夹名作为标签，跨文件夹同图自动合并），原文件夹保留待你核对。

## ⌨️ 指令

指令组 `pic`（子指令中英文都认；🔒 表示需要管理员；下方 `<短hash>` 都可改成「引用那张图」）。

| 指令 | 中文别名 | 说明 | 权限 |
|------|----------|------|:----:|
| `pic save <标签...>` | `pic 存图` | 带图/引用图，存图并打标签 | 🔒 |
| `pic tag [短hash] <标签...>` | `pic 打标` | 给图追加标签（一图多义） | 🔒 |
| `pic untag [短hash] <标签...>` | `pic 去标` | 移除标签，清空则删图 | 🔒 |
| `pic delete [短hash...]` | `pic 删图` | 删除图片 | 🔒 |
| `pic gc` | `pic 清理` | 手动清理无用图片 | 🔒 |
| `pic view <标签>` | `pic 看图` | 查看该标签下所有图（拼图，标注短hash） | |
| `pic view <短hash>` | `pic 看图` | 查看单张原图 | |
| `pic tags` | `pic 标签` | 列出所有标签及数量 | |
| `pic info [短hash]` | `pic 信息` | 查看某图的标签 / 创建者 | |
| `pic help` | `pic 帮助` | 查看帮助 | |

示例：`pic save 开心 搞笑`、引用一张图 + `pic 删图`、`pic tag 开心`、`pic view 开心`。

## 🤖 LLM 工具

开启函数调用后，大模型可主动使用：

- `list_tags()` —— 列出所有标签及数量
- `send_image_by_tag(tag)` —— 从指定标签随机发一张表情

这样"用户很高兴 → 发个开心表情"由大模型按语义决定，比关键词匹配更准。

## ⚙️ 配置

在 AstrBot 面板：插件管理 → astrbot_plugin_gallery → 插件配置。

- `galleries_dir`：图片池根目录（存 `images/` 与 `index.json`）
- `auto_collect`：自动收集群聊图片并用 LLM 打标签入池（默认关）
- `http_proxy`：外部请求代理

> Docker 部署：务必把消息平台容器与 AstrBot 挂载到同一文件夹，否则无法解析图片路径。

## 🤝 TODO

- [x] 内容寻址图片池 + 自动去重
- [x] 一图多标签（多义）
- [x] 引用图 / 短 hash 操作
- [x] 图片回收（即时 + 启动自愈对账）
- [x] 旧图库文件夹自动迁移
- [x] 注入 LLM 工具（list_tags / send_image_by_tag）
- [ ] embedding 语义检索（`pic search`，让"开心≈高兴"在算法层也打通）

## 📌 致谢

Fork 自 [Zhalslar/astrbot_plugin_gallery](https://github.com/Zhalslar/astrbot_plugin_gallery)，在其基础上重写为标签池架构。
