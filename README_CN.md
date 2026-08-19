# Alexandria 有声书生成器

[English](README.md) | 中文

Alexandria 现在是一个基于文件的 CLI 长篇有声书流水线：使用 Codex CLI 分析章节、维护角色和声音身份、生成 TTS 音频，并将每章发布为 M4B。

旧版 Alexandria 浏览器 UI 及其 HTTP API 已移除。当前支持的流程不启动本地 Web 服务。Audiobookshelf 是独立的可选服务，负责书库管理和播放。

## 当前架构

- cli.py 管理书籍项目、章节映射、分析状态、角色 ID、声音 ID、缓存、断点续跑和 M4B 导出。
- app/tts.py 是共享 TTS 后端，支持本地 Qwen3-TTS 和外部 HTTP/Gradio TTS 端点。
- assets/sfx/ 是内置修仙小说音效库；章节分析生成受控 cue，CLI 使用 FFmpeg 按人声时间轴混音。
- books/<book>/output/chapters/ 是发布目录，Audiobookshelf 从这里扫描章节。
- Codex CLI 以临时只读子进程运行，用于章节分析和摘要生成。

## 环境要求

- 已安装项目 Python 依赖
- 已安装并完成认证的 Codex CLI：codex auth login
- PATH 中可用的 ffmpeg
- 本地 Qwen3-TTS，或已经配置好的外部 TTS 端点
- 本地 TTS 推荐使用 GPU；使用外部 TTS 时本机可以不配 GPU

CLI 默认分析模型为 gpt-5.6-luna，推理档位为 max。需要覆盖时可设置 ALEXANDRIA_CODEX_MODEL 或 ALEXANDRIA_CODEX_REASONING_EFFORT。

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

## 音效与广播剧混音

音效默认启用。项目包含 21 个可重复生成的修仙小说基础音效，以及 28 个用户提供的真实录音变体，包括剑气破空、金铁交击、灵力爆发、法术蓄力/释放、雷击、爆炸、遁光、传送、护罩、脚步、开门、宗门钟声、妖兽咆哮，以及风、雨、森林、洞府、火焰和流水环境音。同一 cue 有多个素材时会根据台词和时间点稳定选择，重复渲染结果一致。

重新生成内置 WAV：

    python3 scripts/generate_builtin_sfx.py

新分析的章节会在 script.json 每句的 effects 数组中保存音效 cue。已有章节需要强制重新分析一次才会自动配音效：

    python3 cli.py analyze --book fanren --chapter 742 --force
    python3 cli.py render --book fanren --chapter 742

也可以手工编辑 script.json：

    "effects": [
      {
        "cue": "sword_clash",
        "position": "after",
        "offset_ms": 250,
        "gain_db": 0,
        "duration_ms": 0,
        "loop": false
      }
    ]

cue 必须存在于 assets/sfx/manifest.json。gain_db 是相对素材默认音量的微调；环境音只有清单中 loop=true 的素材才能循环。渲染后，dialogue.wav 是纯人声母轨，audio.wav 是混音结果，sfx_timeline.json 可用于检查每个音效的绝对时间点。

临时关闭音效：

    ALEXANDRIA_SFX_ENABLED=0 python3 cli.py render --book fanren --chapter 742 --force

可以直接用更高质量的同名 WAV 替换内置素材，也可以在 manifest.json 中增加自己的 cue。

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
    │   ├── dialogue.wav
    │   ├── sfx_timeline.json
    │   └── audio.m4b
    └── output/chapters/

分析和 TTS 状态按章节保存。如果 TTS 失败，下次运行会复用已有分析结果，从音频阶段继续。

## Audiobookshelf

Audiobookshelf 不参与 CLI 生成过程。项目中的 Compose 文件只管理 Audiobookshelf：

    docker compose up -d audiobookshelf

服务地址为 http://localhost:13378，配置保存在 data/audiobookshelf/，书籍通过只读挂载 ./books:/audiobooks:ro 提供给 Audiobookshelf。启用 Audiobookshelf 的 File Watcher 后，新发布的章节会自动被发现。

## 许可证

MIT
