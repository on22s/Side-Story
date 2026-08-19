# Alexandria 有声书生成器

[English](README.md) | 中文

Alexandria 现在是一个基于文件的 CLI 长篇有声书流水线：使用 Codex CLI 分析章节、维护角色和声音身份、生成 TTS 音频，并将每章发布为 M4B。

旧版 Alexandria 浏览器 UI 及其 HTTP API 已移除。当前支持的流程不启动本地 Web 服务。Audiobookshelf 是独立的可选服务，负责书库管理和播放。

## 当前架构

- cli.py 管理书籍项目、章节映射、分析状态、角色 ID、声音 ID、缓存、断点续跑和 M4B 导出。
- app/tts.py 是共享 TTS 后端，支持本地 Qwen3-TTS 和外部 HTTP/Gradio TTS 端点。
- books/<book>/output/chapters/ 是发布目录，Audiobookshelf 从这里扫描章节。
- Codex CLI 以临时只读子进程运行，用于章节分析和摘要生成。

## 环境要求

- 已安装项目 Python 依赖
- 已安装并完成认证的 Codex CLI：codex auth login
- PATH 中可用的 ffmpeg
- 本地 Qwen3-TTS，或已经配置好的外部 TTS 端点
- 本地 TTS 推荐使用 GPU；使用外部 TTS 时本机可以不配 GPU

CLI 默认分析模型为 gpt-5.3-codex-spark，推理档位为 xhigh。需要覆盖时可设置 ALEXANDRIA_CODEX_MODEL 或 ALEXANDRIA_CODEX_REASONING_EFFORT。

## 快速开始

初始化书籍项目：

    python cli.py init --book fanren --input /data/books/fanren.epub --title "凡人修仙传"

先检查章节映射，再生成一段章节范围：

    python generate_chapters.py 742 10 --plan
    python generate_chapters.py 742 10 --continue

章节号使用小说原始章节号，count 包含起始章节。

查看状态或中断后续跑：

    python cli.py status --book fanren
    python cli.py run --book fanren --continue

需要时导出整本 M4B：

    python cli.py export --book fanren --format m4b

只做预检，不调用 Codex 或 TTS：

    python cli.py run --book fanren --from 742 --count 1 --dry-run

## 书籍目录

    books/<book>/
    ├── book.json
    ├── state/
    │   ├── characters.json
    │   ├── aliases.json
    │   ├── voices.json
    │   └── novel_chapters.json
    ├── chapters/000001/
    │   ├── source.txt
    │   ├── script.json
    │   ├── summary.txt
    │   ├── status.json
    │   └── audio.m4b
    └── output/chapters/

分析和 TTS 状态按章节保存。如果 TTS 失败，下次运行会复用已有分析结果，从音频阶段继续。

## Audiobookshelf

Audiobookshelf 不参与 CLI 生成过程。项目中的 Compose 文件只管理 Audiobookshelf：

    docker compose up -d audiobookshelf

服务地址为 http://localhost:13378，配置保存在 data/audiobookshelf/，书籍通过只读挂载 ./books:/audiobooks:ro 提供给 Audiobookshelf。启用 Audiobookshelf 的 File Watcher 后，新发布的章节会自动被发现。

## 许可证

MIT
