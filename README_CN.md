# Alexandria 有声书生成器

[English](README.md) | 中文

Alexandria 现在是一个基于文件的 CLI 长篇有声书流水线：使用 Codex CLI 分析章节、维护角色和声音身份、生成 TTS 音频，并将每章发布为 M4B。

旧版 Alexandria 浏览器 UI 及其 HTTP API 已移除。当前支持的流程不启动本地 Web 服务。Audiobookshelf 是独立的可选服务，负责书库管理和播放。

## 当前架构

- cli.py 管理书籍项目、章节映射、分析状态、角色 ID、声音 ID、缓存、断点续跑和 M4B 导出。
- app/tts.py 是共享 TTS 后端，支持本地 Qwen3-TTS 和外部 HTTP/Gradio TTS 端点。
- assets/sfx/ 是内置修仙小说音效库；章节分析生成受控 cue，CLI 使用 FFmpeg 按人声时间轴混音。
- Dasheng-AudioGen 可作为独立的外部 `/sfx` HTTP 后端；本机通过 SSH 隧道调用，不与 TTS `/tts` 接口混用。
- books/<book>/output/chapter_sources/ 保存单章源文件，不提供给 Audiobookshelf 扫描。
- books/<book>/output/chapters/ 只保存固定文件名的合并版，Audiobookshelf 从这里扫描。
- 音频约定：内部旁白/音效混音使用 48 kHz、单声道、PCM 16-bit WAV；章节和滚动合并版发布为 AAC-LC、44.1 kHz、单声道、96 kbps，并开启 faststart。
- Codex CLI 以临时只读子进程运行，用于章节分析和摘要生成。

## 环境要求

- 已安装项目 Python 依赖
- 已安装并完成认证的 Codex CLI：codex auth login
- PATH 中可用的 ffmpeg
- 本地 Qwen3-TTS，或已经配置好的外部 TTS 端点
- 使用默认的 127.0.0.1:18000/18001 xc 端点时，CLI 渲染前会自动通过 SSH 检测并拉起 xc 上的两个服务，建立/复用隧道并等待 /health 就绪；设置 ALEXANDRIA_XC_TTS_AUTO_START=0 可关闭。
- 当前 `app/config.json` 使用已由 Dasheng 重生成的 manifest 素材；如需后续按 cue 动态生成，可将 SFX provider 改为 Dasheng，CLI 会自动拉起 `xc` 服务并建立 127.0.0.1:18100 隧道。手动启动隧道可运行 `ALEXANDRIA_XC_SFX_BACKGROUND=1 ./start_xc_sfx_tunnel.sh`。
- 本地 TTS 推荐使用 GPU；使用外部 TTS 时本机可以不配 GPU

CLI 默认分析模型为 gpt-5.6-luna，推理档位为 max。需要覆盖时可设置 ALEXANDRIA_CODEX_MODEL 或 ALEXANDRIA_CODEX_REASONING_EFFORT。

逐字覆盖校验默认关闭，少字、多字或轻微改写不会阻断生成。仅在排查文本问题时显式设置 `ALEXANDRIA_COVERAGE_MODE=warn` 或 `strict`。

## 快速开始

初始化书籍项目：

    python cli.py init --book fanren --input /data/books/fanren.epub --title "凡人修仙传"

先检查章节映射，再生成一段章节范围：

    python generate_chapters.py 742 10 --plan
    python generate_chapters.py 742 10 --continue

章节号使用小说原始章节号，count 包含起始章节。

需要并行分析并流水线渲染 TTS 时，使用可配置 worker 数的协调脚本；分析完成一章就会进入渲染，渲染期间继续分析其他章节：

    .venv/bin/python scripts/generate_parallel.py 774 10 --continue --workers 8

默认会在渲染前自动检查并通过 SSH 拉起 xc TTS 服务。

查看状态或中断后续跑：

    python cli.py status --book fanren
    python cli.py run --book fanren --continue

需要时导出整本 M4B：

    python cli.py export --book fanren --format m4b

只做预检，不调用 Codex 或 TTS：

    python cli.py run --book fanren --from 742 --count 1 --dry-run

## 按书配置

全局 `app/config.json` 继续作为所有书的默认配置；`books/<book>/config.json` 是可选的书级覆盖，并按字段深度合并。没有写在书级文件里的 TTS 地址、超时、并行度等字段，仍然继承全局值。

英文书可以在初始化时直接指定：

    python cli.py init --book english-book --input /data/books/novel.txt --language English --voice-preset english_narrator

这会写入 `books/english-book/config.json`，并让该书使用英文提示词、English TTS language 和英文旁白 preset。也可以手工编辑书级配置，例如：

    {
      "language": {"source": "en", "tts": "English", "prompt": "en"},
      "tts": {
        "voice_preset": "english_narrator"
      },
      "sfx": {"enabled": false}
    }

示例故意没有写 TTS URL；这样仍使用全局 `app/config.json` 的地址。`--prompt-locale en` 可单独切换 Codex 提示词语言，`--disable-sfx` 可关闭该书的音效混音。

修改书级配置后，下一次运行会按影响范围自动失效：语言/提示词变化会重新分析脚本和摘要；声音、TTS 或音效参数变化只会重新渲染音频。

## 音效与广播剧混音

音效默认启用。项目包含 21 个可重复生成的修仙小说基础音效，以及 28 个用户提供的真实录音变体，包括剑气破空、金铁交击、灵力爆发、法术蓄力/释放、雷击、爆炸、遁光、传送、护罩、脚步、开门、宗门钟声、妖兽咆哮，以及风、雨、森林、洞府、火焰和流水环境音。同一 cue 有多个素材时会根据台词和时间点稳定选择，重复渲染结果一致。

启用 Dasheng 后，现有 `manifest.json` 中的 cue 会按其描述生成 WAV，并写入每本书的 `cache/sfx`；生成结果会复用现有 `sfx_timeline.json` 和 FFmpeg 混音流程。配置示例：

    "sfx": {
      "provider": "builtin",
      "auto_generate_missing": true,
      "url": "http://127.0.0.1:18100/sfx",
      "cache_dir": "cache/sfx",
      "fallback_to_manifest": true
    }

当 `auto_generate_missing` 为 true 时，已有静态素材优先直接使用；脚本里出现 manifest 没有的 cue，或 manifest 中的素材文件缺失，渲染当前章节时会自动通过 xc 上的 Dasheng 生成并缓存到每本书的 `cache/sfx`，随后立即进入当前章混音。若服务失败且存在静态素材则回退，若没有可回退素材则明确报错。该流程只为脚本已经标记的音效生成，不会凭空给普通文本添加音效。

远端 Dasheng 部署目录为 `/mnt/workspace/xinchao.gou/Dasheng-AudioGen`，服务端口为 `8100`，本机隧道端口为 `18100`。Dasheng 原生生成约 10 秒音频，章节混音阶段负责按 cue 的 `duration_ms` 裁剪或循环。

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

通常 cue 应存在于 `assets/sfx/manifest.json`，这样可以提供更准确的类别、描述和循环属性；开启 `auto_generate_missing` 后，原文中明确出现但目录没有的 cue 也会按需生成。`gain_db` 是相对素材默认音量的微调；环境音只有清单中 `loop=true` 的素材才能循环。渲染后，`dialogue.wav` 是纯人声母轨，`audio.wav` 是混音结果，`sfx_timeline.json` 可用于检查每个音效的绝对时间点。

临时关闭音效：

    ALEXANDRIA_SFX_ENABLED=0 python3 cli.py render --book fanren --chapter 742 --force

可以直接用更高质量的同名 WAV 替换内置素材，也可以在 manifest.json 中增加自己的 cue。

## 书籍目录

    books/<book>/
    ├── book.json
    ├── config.json          # 可选：按书覆盖全局配置
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
    └── output/
        ├── chapter_sources/
        └── chapters/        # 仅合并版

分析和 TTS 状态按章节保存。如果 TTS 失败，下次运行会复用已有分析结果，从音频阶段继续。

## Audiobookshelf

Audiobookshelf 不参与 CLI 生成过程。项目中的 Compose 文件只管理 Audiobookshelf：

    docker compose up -d audiobookshelf

服务地址为 http://localhost:13378，配置保存在 data/audiobookshelf/，书籍通过只读挂载 ./books:/audiobooks:ro 提供给 Audiobookshelf。启用 Audiobookshelf 的 File Watcher 后，新发布的章节会自动被发现。

更新《凡人修仙传》固定合并版时，使用一键命令：

    .venv/bin/python scripts/update_serial.py

默认从第 757 章开始，自动找到连续生成的最新章节，然后依次完成导出、轻量章节校验、原子发布和手机端 API 校验。单章音频始终保留，但合并音频只保留 `output/chapters/fanren_serial.m4b` 一个版本；导出过程产生的范围版在发布成功后自动删除。如果目录章节不一致，脚本会先停止容器并备份 SQLite，只把 M4B 的章节、时长和文件元数据同步到当前合并版记录，再启动服务并延迟复核。若 Audiobookshelf 现有条目指向 `/audiobooks` 挂载内的另一个路径，脚本还会先把新合并版原子同步到该实际扫描路径，避免项目目录和书库文件分叉。它不会重建书籍条目，因此保留原有播放进度；也不必等待不可靠的文件监听或耗时的全库扫描。

常用选项：

    # 只查看本次将合并到哪一章
    .venv/bin/python scripts/update_serial.py --dry-run

    # 强制重新编码，或只发布本地文件、不操作 Audiobookshelf
    .venv/bin/python scripts/update_serial.py --force
    .venv/bin/python scripts/update_serial.py --skip-audiobookshelf

脚本只有在 Audiobookshelf API 返回的章节数和末章都正确后才报告完成。批量章节生成完后运行一次即可，不需要每生成一章就重编码整个合并版。

## 许可证

MIT
