<img src="icon.png" alt="Alexandria 标志" width="160" />

# Alexandria Audiobook Nya

将书籍制作成多角色配音有声书。Alexandria 将 AI 脚本标注、本地 Qwen3-TTS 和浏览器编辑器结合起来，让你为角色分配声音、试听并修改单独的语音片段，最后导出整本有声书。

**[安装](#安装) · [快速入门](#快速入门) · [可选声音工具](#可选-voice-lab--preparer-依赖) · [常见问题](#常见问题) · [完整使用指南（英文）](https://github.com/on22s/alexandria-audiobook-nya/wiki)**

[English](README.md) | 中文

## 主要功能

- **导入书籍**：支持 TXT、Markdown 和 EPUB，生成带说话人标签和演绎指令的可编辑脚本。
- **构建配音阵容**：使用预置声音、参考音频克隆、声音设计或 LoRA 适配器；可跨书籍复用声音库与系列角色阵容。
- **先试听，再导出**：逐段编辑文本、说话人和指令，选择性重新生成，并检查文本完整性与声音一致性。
- **灵活导出**：合并 MP3、带章节的 M4B、单独语音行或章节，以及供 Audacity 使用的按说话人分轨音频。
- **按需选择运行方式**：本地运行 TTS，或连接外部 Qwen3-TTS Gradio 服务。自动脚本标注使用兼容 OpenAI API 的本地或远程 LLM；也可采用手动复制粘贴模式。

从五个带编号的标签页开始：**Setup（设置）→ Script（脚本）→ Voices（声音）→ Editor（编辑器）→ Result（结果）**。Designer、Dataset、Training、Preparer、Voice Lab 和 Reports 是按需使用的高级工具。下文保留界面中的英文按钮名称，方便查找。

## 安装

### Pinokio（推荐）

1. 安装 [Pinokio](https://pinokio.computer/)。
2. 点击 **Download**，粘贴 `https://github.com/on22s/alexandria-audiobook-nya`。
3. 点击 **Install**，完成后依次点击 **Start** 和 **Open Web UI**。
4. 按[快速入门](#快速入门)配置 LLM，先用一小段文本试做有声书。

常规安装包含有声书应用和 Qwen3-TTS 运行环境。TTS 权重在首次使用时下载；LLM 权重需另行准备。**Install Voice Tools (Optional)** 用于 Preparer / Voice Lab 的原生处理阶段及随附的本地 LLM 启动器，基本有声书流程不需要安装它。

全新安装会以 CPython 3.10 创建 `app/env`，先安装适合当前平台的 PyTorch，再安装其他依赖。已有环境会保留。处理整本书前，请先阅读[系统要求](#系统要求)和[首次启动](#首次启动)。

## 快速入门

### 第 1 步 — Setup（设置）

自动标注模式需要配置 LLM 连接及 TTS 引擎：

- **LLM Base URL**：LM Studio 通常为 `http://localhost:1234/v1`，Ollama 为 `http://localhost:11434/v1`。
- **LLM API Key**：服务所需的密钥；本地服务可填写 `local`。
- **LLM Model Name**：填写服务实际提供的准确模型 ID。
- **TTS Mode**：推荐 `local`，直接加载内置模型，无需外部 TTS 服务。
- 选择本地或远程服务配置，并准确设置 **Runs on this machine's GPU?**，以便脚本和音频任务安全共用 GPU。
- 完成后点击 **Save Configuration**。

没有 API 服务时，可选择手动传输模式，在 Script 标签页复制请求、粘贴模型回复。此模式不使用 API 地址；长书需要多次人工操作。

### 第 2 步 — Script（脚本）

- 用文件选择器选取 `.txt`、`.md` 或 `.epub`，文件会自动上传。
- 点击 **Generate Annotated Script**。自动模式会将书籍发送给所配置的 LLM，生成带说话人标签和演绎指令的片段。
- 如有需要，点击 **Review Script**，让 LLM 再次检查说话人归属和格式等问题。
- 长任务可使用快照和续跑功能；批处理可处理多本书。Windows 不支持暂停，可使用 Cancel 取消后再点击 Generate，从检查点继续。
- 使用保存功能保留脚本，便于下次加载。

### 第 3 步 — Voices（声音）

脚本中的每个角色都会有一张声音卡片：

- 选择 Custom Voice（预置声音，最易上手）、Clone Voice、LoRA Voice、Voice Design 或 Character Ensemble。外部 TTS 模式支持预置声音和克隆；Voice Design 与 LoRA 需要本地 TTS。
- Custom Voice 提供 9 个预设：Aiden、Dylan、Eric、Ono_anna、Ryan、Serena、Sohee、Uncle_fu、Vivian。可设置角色风格，例如“沉稳的旁白语调”。
- **Generate Personas**：让 LLM 分析脚本，为角色生成声音描述、参考音频，并分配克隆声音。**Advanced** 可调整发现角色时的批量大小；通过 **Apply to** 选择只处理尚未分配声音的角色，或重新生成全部角色；运行前确认范围，整书生成前请先试听。
- **Alias of**：将多个名字映射到同一角色的声音，例如“年轻的艾琳娜” → “艾琳娜”。别名会沿引用链解析，并检测循环引用。
- 更改会自动保存。详细说明见 [Voices 指南（英文）](https://github.com/on22s/alexandria-audiobook-nya/wiki/Voices)。

克隆声音需要干净的参考音频及其准确转录文本。导入参考片段需通过应用的 3–30 秒时长、音频质量和使用权确认检查。克隆模式不使用 `instruct` 演绎指令；LoRA 模式则结合训练得到的声音身份与指令控制。随应用附带 LoRA 预设清单，适配器权重按需从 Hugging Face 下载。

### 第 4 步 — Editor（编辑器）

- 点击 **Render Pending** 生成待处理片段。
- 试听单个片段，或用 **Play Sequence** 顺序播放。
- 直接编辑文本、说话人或 `instruct`，再单独重新生成。
- 检查 **Text integrity**（文本完整性）和 **Check Voices**（声音检查）。
- 确认无误后点击 **Merge All** 合并有声书。

**Render Pending** 会自动选择处理方式：本地 TTS 使用批量生成，外部 TTS 使用并行请求。主界面没有独立的 Standard / Batch (Fast) 切换按钮。Custom、Clone、LoRA 支持本地批量生成；Voice Design 和 Ensemble 按顺序生成。先用小批量测试，再按显存余量调整 **Parallel Workers** 和 **Max Items/Batch**。

### 第 5 步 — Result（结果）

- 在浏览器中试听成品，下载合并后的 MP3。
- 导出 **M4B**（AAC），填写书名、作者、朗读者等元数据，并嵌入封面与章节标记。默认从脚本标题识别章节；启用 **Per-chunk chapters** 可让每个片段成为一章。
- **Export to Audacity** 会导出按说话人分轨的 WAV 压缩包。解压后用 Audacity 打开 `project.lof`，再通过 File → Import → Labels 导入 `labels.txt`。

各说话人轨道使用静音补齐到相同长度，同时播放即可还原时间线。M4B 播放器需支持 AAC 和内嵌章节标记；部分播放器的支持有限。

### 高级工具（可选）

- **Designer**：通过文字描述创建声音，试听并保存到声音库，供克隆参考使用。
- **Dataset**：逐条构建 LoRA 训练样本，设置文本与情绪/风格，支持预览、批量生成及取消后保留已完成样本。
- **Training**：训练 LoRA 适配器。可导入包含 24 kHz 单声道 WAV 与 `metadata.jsonl` 的 ZIP；元数据使用 `audio_filepath` 和 `text` 字段。按数据与硬件调整训练参数，先用未参与训练的句子验证效果。
- **Preparer**：将有声书音频与原文对齐，生成训练配对；需先安装可选 Voice Tools。
- **Voice Lab**：检查数据集、训练适配器、分析声音特征并命名；原生处理阶段需要可选依赖及正确的模型路径。
- **Reports**：查看运行历史、产物与诊断信息。

<details>
<summary>更多功能</summary>

- **三阶段脚本标注**：依次进行分段、说话人归属和演绎指令生成，可编辑各阶段提示词预设，并利用前后文。
- **可恢复任务**：快照、失败后续跑和多书批处理；暂停功能受平台限制。
- **服务配置**：分别保存本地/远程 LLM 设置，支持超时、重试、自定义服务选项及可选故障切换。
- **脚本审校**：可检查说话人、旁白/对话边界和演绎指令，并核对原文保留情况。
- **跨书复用**：声音库、系列角色阵容和随故事时间线变化的角色风格。
- **多语言 TTS**：中文、英语、法语、德语、意大利语、日语、韩语、葡萄牙语、俄语、西班牙语，或自动检测。
- **停顿控制**：不同说话人之间默认停顿 500 ms，同一说话人的片段之间默认 250 ms。
- **状态与诊断**：GPU/磁盘状态、任务日志、运行历史和导出前质量检查。
- **章节导出**：按章节导出，支持文件名模板及就绪检查。

</details>

## 系统要求

- 实用的本地 TTS 生成建议使用 GPU。CPU 模式可用，但较慢。显存需求取决于模型、批量大小及是否与 LLM 共用 GPU，没有适用于所有设备的安全批量值。
- 每个 TTS 模型变体需要数 GB 磁盘空间；还需为 Python/PyTorch 环境、可选 LLM 权重、原书及输出音频留空间。下载与工作数据可能持续增长。
- 自动标注需要可访问的 OpenAI 兼容 LLM 接口；手动模式无需 API 服务。本地 TTS 本身无需外部 TTS 服务。

### GPU 兼容性

下表说明安装器采用的路径，不保证每张显卡或每个驱动版本都可用：

| 平台 | 本地 TTS 路径 | 注意事项 |
| --- | --- | --- |
| NVIDIA / Windows 或 Linux | PyTorch 2.7 / CUDA 12.8 | 需要兼容的显卡与驱动；可选 attention wheel 是否可用取决于 Python 和平台 |
| AMD / Linux | PyTorch 2.10 / ROCm 7.0 | 核对显卡及宿主机 ROCm/驱动兼容性；安装器标注的测试目标是 RX 9070 XT / RDNA4，并非所有 AMD 显卡 |
| AMD / Windows | CPU | 此安装器不提供 Windows 下的 AMD GPU 加速 |
| Apple Silicon / macOS | 可用时选择 MPS，否则 CPU | PyTorch 报告 MPS 可用时，`auto` 会选用它；不保证端到端性能与兼容性 |
| Intel / macOS | CPU 回退 | 安装器使用较旧的 PyTorch 固定版本，请先用短文本验证 |
| 其他纯 CPU 环境 | CPU | 生成较慢，请从小样本开始 |

准确版本见 [torch.js](torch.js)，运行时设备选择见 [app/device_utils.py](app/device_utils.py)。随附的 Docker Compose 面向 NVIDIA GPU，不能直接作为 AMD 部署方案。

## 首次启动

### LLM 与 TTS 是两套模型

自动脚本生成前，先启动并加载自己的 LLM 服务，例如 LM Studio、Ollama 或兼容的托管 API。选择能够遵循指令并返回指定结构的模型，先测试一小段文本；上下文容量、质量与内存需求各不相同。

Docker 容器中的 `localhost` 指容器本身，不是宿主机上的 LLM 服务。远程 LLM 服务会收到提交的标注/审校文本；外部 TTS 服务会收到生成输入，克隆时包括参考音频及转录文本。请只处理你有权使用的书籍与参考声音。

如果模型输出推理过程而非所需答案，请使用该模型/服务支持的非思考设置。**Banned Tokens** 不是通用的关闭思考方法。可选本地 LLM 启动器也不自动下载 GGUF 权重。

### 首次 TTS 下载与预热

TTS 权重在首次使用相应变体时下载，通常每个变体约 3.5 GB。CustomVoice、Base/克隆、VoiceDesign 按需加载。下载进度、模型加载及错误详情请查看 Pinokio 的 **Terminal**；等待下载不等于生成已完成。

首次加载、GPU 内核调优和可选 **Compile Codec** 可能增加预热时间。是否更快、快多少取决于硬件和软件栈，不应套用固定的吞吐量或预热时长。

### 显存与日志

先用较小的 **Parallel Workers** / **Max Items/Batch**。LLM 和 TTS 共用显卡时留出余量，并关闭其他占用 GPU 的程序。切换声音类型可能需要重新加载模型。出错时先查看 Terminal 和 Reports，记录完整错误，而不是盲目替换 PyTorch 或驱动。

## 更新与数据安全

**Update 前先保存脚本并备份工作。** 启动器会停止正在写入的任务、拉取代码并重新运行核心安装器，但不能保证中断任务一定可恢复。可选依赖有变化时，请停止应用并重新运行 **Install Voice Tools (Optional)**。

普通 Pinokio/本地安装应备份 `app/config.json`、当前项目的 JSON 文件、`app/uploads/`、`voicelines/`、已保存脚本及声音/数据集/模型库。这些生成文件不会由 Git 自动备份。`ALEXANDRIA_DATA_DIR` 可移动应用数据目录，`ALEXANDRIA_CONFIG_PATH` 独立指定配置文件；请备份实际配置的路径。

**Reset 会删除当前项目数据。** 它会删除默认位置的当前脚本、声音分配、片段/状态文件、生成的语音、合并 MP3 及 `app/config.json`，保留可复用的库。当前重置脚本针对默认仓库路径，不应假定它也会清空自定义数据/配置目录。操作前请核对 [reset.js](reset.js)。

## 其他安装方式与可选工具

### 可选 Voice Lab / Preparer 依赖

在 Pinokio 中停止应用，点击 **Install Voice Tools (Optional)**。此安装流程与核心有声书环境分开：

- 按平台为 CUDA、HIP、Metal 或 CPU 构建 `llama-cpp-python`。
- 在所有平台创建独立的 `preparer_env`，使用自己的 PyTorch 版本约束。
- 获取、校验并构建固定版本的 whisper.cpp 源码和模型。
- 仅在 Linux AMD 路径安装说话人分离组件，该路径的 PyTorch 固定版本满足 pyannote 4 的 `torch>=2.8` 要求。其他平台路径不满足，请勿直接把 pyannote 加进 `app/env`。

原生构建需要 CMake、可用的 C/C++ 工具链，GPU 构建还需匹配的 CUDA/ROCm SDK。请预留下载时间和磁盘空间，并在工具中配置模型及解释器路径。说话人分离还需要 Hugging Face 令牌，并接受 [Community-1 模型条款](https://huggingface.co/pyannote/speaker-diarization-community-1)。核心有声书流程不需要这些可选依赖。

#### 命令行准备与审校

安装可选 Voice Tools 后，在仓库根目录运行。Windows 请将 `preparer_env/bin/python` 替换为 `preparer_env\Scripts\python.exe`。

```bash
# 将音频目录与 EPUB/TXT 原文目录配对处理
preparer_env/bin/python alexandria_batch_processor.py --folder /path/to/audio --source-folder /path/to/books --model /path/to/model.gguf

# 查看对照原文审校、批准数据集修正的用法
preparer_env/bin/python alexandria_compare.py --help

# 检查核心环境；加 --voice-tools 检查可选环境，加 --json 输出 JSON
python env_doctor.py
```

- `preparer_env/bin/python download_model.py` 下载旧版、独立的 Whisper-base Transformers 离线模型到 `models/whisper-base`；它不下载 GGUF LLM，也不替代当前 whisper.cpp 安装。
- Linux 的 `bash run_with_restart.sh --audio /path/to/book.wav --source /path/to/book.epub --model /path/to/model.gguf --output /path/to/dataset.zip` 提供有限次数重试和检查点续跑，并保留共享 GPU 锁。默认优先使用 `preparer_env/bin/python`；可用 `ALEXANDRIA_PREPARER_PYTHON` 指定已准备好的其他解释器。`MAX_RETRIES` 和 `BACKOFF_SECONDS` 控制次数与间隔。
- `corpus_alignment_prescan.py` 检查多本书的初始对齐；`corpus_run_report.py` 运行准备流程并报告经过验证的输出回执。两者接受 `--repo`、`--pairs`、`--output-dir`，新建报告任务需 `--model`，可另设 `--fallback`。配对文件为 JSON 数组，例如 `[{"audio":"/path/book.wav","source":"/path/book.epub","output_name":"book.zip"}]`。它们调用 Linux 重启包装脚本，需要同样的可选环境；完整选项见 `--help`。

#### 本地 LLM 启动器及运行诊断

安装可选 Voice Tools 后，Pinokio 的 **Start LLM** 操作会从仓库根目录加载所选 GGUF 并更新本地 LLM 配置。权重不会自动下载。Reset 和 Update 会先停止这个服务。

若已在 Linux 单独安装原生 `llama-server`，可使用 `start_llama_server.sh` / `ensure_llama_server.sh`，它们保留经过验证的模型/适配器身份及生命周期锁。需显式设置 `LLAMA_BIN`、`LLAMA_MODEL`，并按需设置 `LLAMA_PORT` / `LLAMA_LOG`；脚本不会安装二进制或模型。

以下命令使用应用环境；Windows 将 `app/env/bin/python` 替换为 `app\env\Scripts\python.exe`，Docker 中用 `python`：

- `app/env/bin/python app/analyze_generation_attempts.py --json`：汇总已保存的生成质量记录。
- `app/env/bin/python app/repair_source_llm.py --help`：了解原文修复建议。默认只生成报告，但仍会调用配置的 LLM；写出修复结果需加 `--apply`。
- `app/env/bin/python app/tts_vram_benchmark.py --help`：查看 Custom / Clone 声音的 GPU 批量与编解码器调优用法。实际测试会加载模型并占用 GPU。
- `app/env/bin/python tools/backfill_adapter_digests.py --root /path/to/adapters`：审计缺失的来源摘要。默认不写入，需 `--apply` 才应用；不会覆盖不匹配的既有摘要，也不代表已验证历史训练过程。

### Google Colab

随附 notebook 可在 Colab 中安装、运行应用。GPU 是否可用及会话限制取决于 Colab，不保证免费 GPU 资源。

[![在 Colab 中打开](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/on22s/alexandria-audiobook-nya/blob/main/alexandria_colab.ipynb)

notebook 使用 Google Drive 持久化和 Colab 内置页面端口转发，无需 ngrok 账号。完整步骤见 notebook。

### Docker（NVIDIA GPU）

```bash
git clone https://github.com/on22s/alexandria-audiobook-nya.git
cd alexandria-audiobook-nya
docker compose up --build
```

需要 [Docker](https://docs.docker.com/get-docker/) 和 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)。Web UI 地址为 `http://localhost:4200`。TTS 模型首次使用时下载并缓存到 Docker 卷，用户数据通过绑定挂载保存在项目目录。

升级前备份 `data/`，保留原项目目录及模型缓存卷。新状态使用 `ALEXANDRIA_DATA_DIR=/alexandria/runtime`，挂载自 `./data/runtime`。原有 `data/uploads`、`data/scripts`、`data/designed_voices`、`data/clone_voices`、`data/lora_models`、`data/lora_datasets`、`data/dataset_builder` 和 `data/output` 仍挂载到对应运行时目录，无需移动宿主机数据。更多路径兼容细节见[英文 Docker 说明](README.md#docker-data-and-upgrades)。

默认镜像包含命令行脚本，但不构建原生 Voice Tools，也不创建 `preparer_env`。准备数据集时需通过 `ALEXANDRIA_PREPARER_PYTHON` 指定另行配置的解释器；普通有声书生成不受影响。原生 LLM 服务的 shell 启动器面向准备好的 Linux 仓库环境，不适用于基础 Docker 镜像。

#### 网络安全

Compose 只将端口发布到 `127.0.0.1:4200`；容器内部绑定 `0.0.0.0` 以便 Docker 转发。**默认不启用身份认证。** 暴露宿主机端口、使用隧道或添加反向代理之前，请在容器环境中设置 `ALEXANDRIA_AUTH_PASSWORD`，并按需设置 `ALEXANDRIA_AUTH_USERNAME`（默认 `alexandria`）。在可信本地网络之外访问时请使用 HTTPS。

使用域名时，将 `ALEXANDRIA_ALLOWED_HOSTS` 设为对应主机名。另一 Web origin 需要在浏览器中调用 API 时，将其准确 origin 加入 `CORS_ORIGINS`（多个值以逗号分隔）。该列表同时用于 CORS 和请求来源检查；`ALEXANDRIA_ALLOWED_ORIGINS` 只扩展来源检查的允许列表，单独设置它不足以启用浏览器跨源 API 访问。主机名/origin 检查不能替代身份认证。不要将凭据写入镜像或提交到 Compose 文件。

## 中文书籍与提示词

- 在 Setup 的 **Language** 中选择 **Chinese** 或 **Auto**。
- 在 **Setup → Prompt Settings (Advanced)** 中分别编辑分段（Step 1）、说话人归属（Step 2）、演绎指令（Step 3）、审校及角色提示词。根据中文对话、引号与称谓习惯调整；用 **What the model will see** 查看说话人归属请求。
- 点击 **Save Configuration** 或 **Save preset and Setup** 才会保存更改。**Reset to Defaults** 只替换表单内容，之后仍需保存。
- 默认来源为 [app/default_prompts_segment.txt](app/default_prompts_segment.txt)、[app/default_prompts_instruct.txt](app/default_prompts_instruct.txt)、[app/attribution_prompt_variants.py](app/attribution_prompt_variants.py)（默认形态另见 [app/default_prompts_attribute.txt](app/default_prompts_attribute.txt)），以及 [review_prompts.txt](review_prompts.txt) 和 [persona_prompts.txt](persona_prompts.txt)。
- 根目录的 `default_prompts.txt` 属于旧版单阶段生成器，只改它不会自定义当前的三阶段流程。
- 标注流程会尽量保留原文字词，将演绎指令单独存放。生成后仍需检查文本完整性与角色归属；原文中的感叹、笑声等有声表达应留在文本中。

## 常见问题

### 脚本生成失败

确认 LLM 服务已启动、地址可访问、模型 ID 与服务一致。检查完整日志，并用短文本测试模型是否能返回指定结构。模型输出推理过程时，使用服务支持的非思考设置；不要把禁止 `<think>` 当作通用修复。

### 模型下载慢或失败

模型首次使用时从 Hugging Face 下载，每个 TTS 变体通常约 3.5 GB。中国大陆等网络受限环境可在启动前设置 `HF_ENDPOINT=https://hf-mirror.com`。这是第三方镜像，使用前请自行确认其可信度；不使用镜像时保留官方端点。

也可在 `start.js` 已有的 `env` 对象内增加 `HF_ENDPOINT`，不要覆盖其他环境变量。下载中断后可重启重试，可恢复程度取决于下载器及缓存。官方服务的访问/限流问题可按 Hugging Face 指引配置 `HF_TOKEN`；不要在 Issue、截图或日志中公开令牌，也不要将令牌发送给不信任的镜像。

### TTS 生成失败或显存不足

查看 Terminal 中的模型加载错误，降低 **Parallel Workers** / **Max Items/Batch**，关闭其他占用 GPU 的程序。外部模式还需确认 Gradio TTS 服务运行正常。检查声音设置、参考音频及准确转录文本；必要时用 CPU 作为较慢的回退方案。

### 生成速度慢

首次下载、加载和预热通常较慢。可按当前软硬件支持情况尝试 **Compile Codec**，预热后再比较性能；显存允许时逐步增加批量。**Render Pending** 已会自动选择本地批量处理。AMD 问题请核对完整错误和 ROCm/PyTorch 版本，不能将所有 MIOpen 警告视为同一原因。

### MP3 文件损坏或很小（428 字节）

如果 FFmpeg 缺少 `libmp3lame` 编码器，单个片段可回退为 WAV，但合并 MP3 仍需要正常的 MP3 编码支持。可安装带 MP3 支持的 FFmpeg（如 `conda install -c conda-forge ffmpeg`），或在确认系统已有可用版本后移除 Conda 的 FFmpeg。Linux/macOS 可用 `ffmpeg -encoders 2>/dev/null | grep mp3` 检查。

### 声音质量或乱码

使用干净、无背景噪声且转录准确的参考音频；预置声音可尝试不同随机种子。已知编码问题可能在内存中修复，不修改源文件；未解决的问题会报告。持续出现乱码时，请检查输入文本是否为 UTF-8。

<details>
<summary>脚本格式、输出文件与 API</summary>

## 脚本格式

脚本是包含 `speaker`、`text` 和 `instruct` 的 JSON 数组：

```json
[
  {"speaker": "NARRATOR", "text": "门缓缓地开了。", "instruct": "Calm, even narration."},
  {"speaker": "艾琳娜", "text": "谁在那里？", "instruct": "A startled, whispered question."}
]
```

`instruct` 是简短的语调和演绎指令，与原文分开；不同声音模式对指令的支持不同。标注不能保证完全忠于原文，请在生成和合并前检查。

## 输出文件

- `ALEXANDRIA_DATA_DIR` 可指定可变应用数据目录；`ALEXANDRIA_CONFIG_PATH` 单独控制配置文件位置。Docker 的默认值及挂载见上文。
- 合并 MP3 为 `cloned_audiobook.mp3`；M4B 为 `audiobook.m4b`。
- 单独语音位于 `voicelines/`，文件名使用片段唯一 ID 和说话人，例如 `voiceline_<uid>_narrator.mp3`。MP3 编码失败时可能为 WAV。文件名不是时间线序号，请以编辑器顺序或元数据为准。
- `audacity_export.zip` 包含 `project.lof`、`labels.txt` 及各说话人的 WAV 轨道。

## API 参考

使用运行中启动器显示的地址。Pinokio 自动选择可用端口；在应用目录直接执行 `python app.py` 时默认是 `http://127.0.0.1:4200`，可用 `ALEXANDRIA_PORT` 更改。

- 交互式接口文档：`<BASE>/docs`；OpenAPI JSON：`<BASE>/openapi.json`。
- 设置 `ALEXANDRIA_AUTH_PASSWORD` 后，请求需 HTTP Basic 认证；默认用户名为 `alexandria`，可用 `ALEXANDRIA_AUTH_USERNAME` 修改。
- 浏览器请求须来自允许的 origin，优先使用同源请求。连接其他 Web 应用前请检查网络安全设置。
- 先检查 HTTP 状态码；任务启动成功不代表任务完成。

### 配置与脚本

- `GET /api/config`：读取配置，API 密钥会脱敏。
- `GET /api/default_prompts`：获取生成各阶段、审校和角色的默认提示词。
- `POST /api/config`：保存配置，包含 `llm`、`tts` 及与 `llm_mode` 对应的 `llm_local` 或 `llm_remote` 配置；字段以接口文档为准。
- `POST /api/upload`：multipart 字段名为 `file`，支持 TXT、MD、EPUB，默认选中上传来源。
- `POST /api/generate_script`：启动或继续当前来源的脚本生成；可选 JSON 字段包括 `strip_front_matter`、`first_person_narrator`、`start_over`。
- `GET /api/annotated_script` / `POST /api/review_script`：读取脚本 / 启动审校。
- `GET /api/scripts`、`POST /api/scripts/save`、`POST /api/scripts/load`：列出、保存、加载脚本；保存/加载使用 `{"name":"my-novel"}`。

### 声音与生成

- `GET /api/voices`：读取说话人及声音配置。
- `POST /api/save_voice_config`：按说话人保存，例如 `{"NARRATOR":{"type":"custom","voice":"Ryan","character_style":"calm"}}`。
- `POST /api/generate_personas`：生成角色及参考音频，对应任务名 `persona`。
- `GET /api/chunks`：读取按编辑器顺序排列的片段数组，包含状态和音频路径。
- `POST /api/chunks/{index}`：修改片段；`POST /api/chunks/{index}/generate`：生成该片段。
- `POST /api/generate_batch` 或 `POST /api/generate_batch_fast`：生成指定数组位置，例如 `{"indices":[0,1,2]}`。这是从 0 开始的位置，不是片段 ID。
- `GET /api/editor/integrity`：合并前核对文本。`POST /api/merge` 启动合并；报告未通过验证且未确认，或提供的确认快照已失效时，会返回 HTTP 409。核对报告后，再将其 `snapshot` 作为 `integrity_confirmation` 明确确认。
- `GET /api/audiobook`：合并完成后下载 MP3。
- `POST /api/export_audacity`：启动分轨导出；`GET /api/export_audacity`：下载 ZIP。
- `POST /api/merge_m4b`：携带 JSON 选项启动 M4B 导出；`GET /api/audiobook_m4b`：下载结果。

### 任务状态

`GET /api/status` 列出已注册的任务名；轮询 `GET /api/status/{task_name}` 查看 `running`、日志和任务专属结果。

| 操作 | 任务名 |
| --- | --- |
| 脚本生成 / 审校 | `script` / `review` |
| 角色生成 | `persona` |
| 片段生成及 MP3 合并 | `audio` |
| Audacity / M4B 导出 | `audacity_export` / `m4b_export` |
| LoRA 训练 | `lora_training` |

启动接口通常返回 `{"status":"started"}`，不是任务 ID。没有统一的 `completed` / `error` 状态字段；`running: false` 只表示已停止，必须检查日志和具体结果。Audacity 导出另有 `result.status`：`done`、`failed` 或 `cancelled`。

客户端流程：上传 → 生成并等待、检查结果 → 按需审校并等待 → 配置声音 → 生成音频并确认目标片段均为 `done` → 核对完整性 → 合并并检查日志 → 下载。其他设计器、数据集、训练和取消接口以 `/docs` 为准。

</details>

## 更多文档

- [Nya 使用指南（英文）](https://github.com/on22s/alexandria-audiobook-nya/wiki)：安装、脚本、声音、编辑器、导出及高级工具。
- [English README](README.md)：英文说明及项目结构。

## 致谢

Alexandria Nya 建立在许多人分享的成果、想法、问题报告和测试反馈之上。感谢最初的 Alexandria 社区，以及所有帮助改进这些分支项目的人。

### 应用、贡献与测试

- [Finrandojin](https://github.com/Finrandojin/alexandria-audiobook)：创建了最初的 Alexandria Audiobook 应用，并提供可下载的 [Alexandria 声音预设](https://huggingface.co/Finrandojin/Alexandria)。
- [Ayush Naphade](https://github.com/aayushnaphade)：贡献了角色声音设定生成、说话人别名解析和结合上下文的脚本审校功能（[上游 PR #42](https://github.com/Finrandojin/alexandria-audiobook/pull/42)）。他的相关项目是 [Lily](https://lily.rayoneai.in/)。
- [Michii / on22s](https://github.com/on22s)：在 [Alexandria Audiobook2](https://github.com/on22s/alexandria-audiobook2) 中所作的改进已引入 Nya，包括贡献至上游的系统健康仪表盘、跨平台子进程运行器和语音训练数据集准备工具（[#45](https://github.com/Finrandojin/alexandria-audiobook/pull/45)、[#46](https://github.com/Finrandojin/alexandria-audiobook/pull/46)、[#47](https://github.com/Finrandojin/alexandria-audiobook/pull/47)）。
- [REFLEXGAMING007](https://github.com/REFLEXGAMING007)：提供了详细的功能提案、问题复现案例和反复测试，推动了这些分支项目中的手动 LLM 工作流、快照、角色声音设定增量更新、可编辑提示词和角色状态声音等功能的完善（[手动生成](https://github.com/on22s/alexandria-audiobook2/issues/593)、[快照](https://github.com/on22s/alexandria-audiobook2/issues/600)、[增量更新](https://github.com/on22s/alexandria-audiobook2/issues/602)、[提示词编辑](https://github.com/on22s/alexandria-audiobook2/issues/634)、[角色状态声音设定](https://github.com/on22s/alexandria-audiobook2/issues/866)）。

- [Alchemist-Production](https://github.com/Alchemist-Production)：最初的 Web UI、音频编辑器和分块管理工作已集成到上游 Alexandria（[集成](https://github.com/Finrandojin/alexandria-audiobook/commit/1667edc237418fbf9e819bfb4294b14209da9c27)、[编辑器](https://github.com/Finrandojin/alexandria-audiobook/commit/717f89161b36ced57c97cea5b729be95b3cba39e)）。
- [PierrunoYT](https://github.com/PierrunoYT)：最初的 HTML 转义安全改进由 on22s 纳入[上游 PR #39](https://github.com/Finrandojin/alexandria-audiobook/pull/39)。
- [Robertoge65](https://github.com/Robertoge65)：修复了外部 TTS 缺少导入的问题（[上游 PR #19](https://github.com/Finrandojin/alexandria-audiobook/pull/19)）；[kishore-1404](https://github.com/kishore-1404)：修正了 CUDA 显存属性的使用（[上游 PR #35](https://github.com/Finrandojin/alexandria-audiobook/pull/35)）。
- [MNeMoNiCuZ](https://github.com/MNeMoNiCuZ)：修复了 Docker 中角色声音设定提示词的打包问题，并通过上游后续的 Docker 更新纳入项目（[原始贡献与署名](https://github.com/Finrandojin/alexandria-audiobook/pull/56#issuecomment-5044676266)）。

<details>
<summary>继承的修复背后的社区报告、想法与测试</summary>

- [ElBiggus](https://github.com/ElBiggus)：提供了早期的 Windows/音频反馈，以及[下载](https://github.com/Finrandojin/alexandria-audiobook/pull/5#issuecomment-3870041305)和 [CPU 加载](https://github.com/Finrandojin/alexandria-audiobook/issues/4)问题报告。
- [1BadAshB](https://github.com/1BadAshB)：测试了批量渲染和取消操作，并[诊断了克隆提示缓存未及时更新的问题](https://github.com/Finrandojin/alexandria-audiobook/issues/17#issuecomment-3940188658)，验证了修复结果。
- [generallogin](https://github.com/generallogin)：提供了[模型缓存加载](https://github.com/Finrandojin/alexandria-audiobook/issues/22)和 [NVIDIA 运行变慢](https://github.com/Finrandojin/alexandria-audiobook/issues/23)的问题报告与测试。
- [ryuhda](https://github.com/ryuhda)：通过韩语 LoRA 测试，帮助定位并验证了[训练/推理预填充问题的修复](https://github.com/Finrandojin/alexandria-audiobook/issues/29#issuecomment-4315574687)。
- [sdbrown67](https://github.com/sdbrown67)：提交了 [LLM 输出格式异常的报告](https://github.com/Finrandojin/alexandria-audiobook/issues/20#issuecomment-3985423529)，推动了更稳健的条目过滤。
- [WirelessRoth](https://github.com/WirelessRoth)：提供了[德语和提示词反馈](https://github.com/Finrandojin/alexandria-audiobook/issues/13)，帮助改进语言控制和可编辑的审校提示词。
- [damajor](https://github.com/damajor)：提供了 [Docker 启动、配置和显存清理问题报告](https://github.com/Finrandojin/alexandria-audiobook/issues/62#issuecomment-5044680044)。
- [futuregadets](https://github.com/futuregadets)：提出了[优先使用 Drive 存储](https://github.com/Finrandojin/alexandria-audiobook/issues/59)和 [Colab 无需 ngrok](https://github.com/Finrandojin/alexandria-audiobook/issues/60)的建议，并被上游采纳。
- [Tortoise17](https://github.com/Tortoise17)：提交了[外部声音克隆的语言问题报告](https://github.com/Finrandojin/alexandria-audiobook/issues/69#issuecomment-5062433885)。
- [starpause](https://github.com/starpause)：参与了 [EPUB 中图片形式章节标题的讨论](https://github.com/Finrandojin/alexandria-audiobook/issues/80#issuecomment-5309266456)，推动了通过目录恢复章节标题的功能（[AA2 实现](https://github.com/on22s/alexandria-audiobook2/pull/314)）。

</details>

### 引入应用的分支成果与想法

- [cjdell](https://github.com/cjdell/alexandria-audiobook)：其 AMD APU 精度修复为 Nya 的 fp32 模型加载路径提供了参考（[移植](https://github.com/on22s/alexandria-audiobook2/pull/573)）。
- [XinchaoGou](https://github.com/XinchaoGou/alexandria-audiobook)：贡献了 OpenAI 推理模型请求处理和通过环境变量引用 API 密钥的方式，并提供了推理控制、克隆参考音频验证、外部 TTS 服务器池和滚动故事上下文的想法（[移植](https://github.com/on22s/alexandria-audiobook2/pull/574)、[推理控制](https://github.com/on22s/alexandria-audiobook2/pull/530)、[参考音频验证](https://github.com/on22s/alexandria-audiobook2/pull/531)、[服务器池](https://github.com/on22s/alexandria-audiobook2/pull/532)）。
- [Darkkingwill](https://github.com/Darkkingwill/alexandria-audiobook)：提供了有关 MP3 比特率的发现，以及可取消合并、导出进度、模型选择和记住标签页的想法；这些功能在 AA2 中独立重新实现后引入 Nya（[比特率](https://github.com/on22s/alexandria-audiobook2/pull/533)、[界面改进](https://github.com/on22s/alexandria-audiobook2/pull/534)）。
- [shangyuok](https://github.com/shangyuok/alexandria-audiobook-gg)：提出了可配置 TTS 生成 token 上限的想法，并与相应的内存估算功能一同实现（[实现](https://github.com/on22s/alexandria-audiobook2/pull/60)）。
- [dudarenok-maker / Castwright](https://github.com/dudarenok-maker/Castwright)：提供了跨书籍记住角色阵容和检查已生成声音一致性的想法，并在 Alexandria 中独立实现（[系列记忆](https://github.com/on22s/alexandria-audiobook2/pull/524)、[声音检查](https://github.com/on22s/alexandria-audiobook2/pull/525)）。
- [Gaspard Michel、Elena V. Epure、Romain Hennequin 和 Christophe Cerisara](https://aclanthology.org/2025.naacl-short.62/)：其引语归属研究是 `michel` 系列提示词的基础，并被改编用于 Alexandria 自身的提示词及前后文处理（[实现](app/attribution_prompt_variants.py)）。

<details>
<summary>研究参考与共享资源</summary>

Nya 也受益于 AA2 背后的研究。以下致谢涵盖实验和评估资源，并不意味着每项实验、数据集或模型都包含在 Nya 的运行环境中。

- [Xiao Zhang / buddies](https://github.com/buddies/alexandria-audiobook)：提供了逐行指令词汇，以及将稳定的声音身份与表达方式指令分离的实验。该词表被移植到 AA2 的研究工具中，由此产生的对比结果为声音身份相关工作提供了参考（[审查](https://github.com/on22s/alexandria-audiobook2/pull/601)、[声音改进](https://github.com/on22s/alexandria-audiobook2/pull/603)）。
- [p0n1](https://github.com/p0n1/epub_to_audiobook)：其标点优先级策略经调整后用于 AA2 能识别引语的文本分块实验。
- [zeropointnine](https://github.com/zeropointnine/tts-audiobook-tool)：其将生成音频转写回文本进行验证、检测截断的想法在 AA2 中进行了探索。
- [Drew Thomasson / VoxNovel](https://github.com/DrewThomasson/VoxNovel)：其 BookNLP 基线促成了引语归属方法的对比；感谢 [David Bamman 和 BookNLP 贡献者](https://github.com/booknlp/booknlp)提供底层的文学自然语言处理成果。
- [nazdridoy](https://github.com/nazdridoy/kokoro-tts)：其声音加权混合的想法在 AA2 中进行了探索；[WhiskeyCoder](https://github.com/WhiskeyCoder/Qwen3-Audiobook-Converter)：其独立得出的 Qwen3-TTS 分块长度发现被用作对比参考。
- [Krishnapriya Vishnubhotla、Adam Hammond 和 Graeme Hirst](https://aclanthology.org/2022.lrec-1.628/) 及 PDNC 标注者；RiQuA 的 [Sean Papay 和 Sebastian Padó](https://aclanthology.org/2020.lrec-1.104/)；以及 [DraCor](https://dracor.org/) 社区：提供了 AA2 引语归属研究所使用的文学标注资源。
- [David K. Elson 和 Kathleen R. McKeown](https://www.cs.columbia.edu/~delson/pubs/AAAI10-ElsonMcKeown.pdf)：其引语归属类别在 AA2 的句法框架实验中进行了探索；[Frank Rudzicz 和 BookNLP-OG 的共同作者](https://arxiv.org/abs/2307.03734)：为端到端引语归属方法的对比提供了参考。
- [CosyVoice 团队](https://github.com/QwenAudio/CosyVoice)：AA2 研究了其语音模型设计思路；CosyVoice 并非 Nya 的运行时依赖。
- [LibriVox](https://librivox.org/) 朗读者、[Project Gutenberg](https://www.gutenberg.org/) 和[青空文库（Aozora Bunko）](https://www.aozora.gr.jp/)志愿者，以及 [LJSpeech](https://keithito.com/LJ-Speech-Dataset/)、[Hi-Fi TTS](https://www.openslr.org/109/)、[AISHELL-3](https://www.openslr.org/93/) 和 [Kokoro Speech Dataset](https://mozilladatacollective.com/datasets/cmmknsho4014wmf087kvq5rc6) 的创建者：提供了用于研究对比的真人朗读和原始文本。
- [Jay Myers](https://www.jaymyersvoiceover.com/blog-ideas/how-audiobook-narrators-make-characters-sound-distinct-believable-and-consistent)、[Malk Williams](https://www.linkedin.com/pulse/character-voices-audiobooks-7-key-considerations-malk-williams)，以及[第三方声明](THIRD_PARTY_NOTICES.md#research-and-industry-practice-consulted)中记录的配音选角指导：提供了保持角色声音一致性，以及让同场景角色的声音形成对比的实践思路。

更多研究来源、具体借鉴内容，以及各资源的权利限制说明，均记录在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 中。

</details>

### 模型与工具

感谢以下项目背后的维护者和贡献者：

- **阿里巴巴 Qwen 团队**的 [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)，为本地语音生成、声音克隆和声音设计提供支持。
- [PyTorch](https://pytorch.org/)、[Hugging Face Transformers](https://github.com/huggingface/transformers) 和 [PEFT](https://github.com/huggingface/peft)，为模型运行和适配器训练提供支持；[SpeechBrain](https://github.com/speechbrain/speechbrain)，为声音检查提供说话人嵌入。
- [FastAPI](https://github.com/fastapi/fastapi) 及 Python 音频生态中的 [pydub](https://github.com/jiaaro/pydub)、[SoundFile](https://github.com/bastibe/python-soundfile)、[librosa](https://github.com/librosa/librosa) 和 [FFmpeg](https://ffmpeg.org/)，支持应用服务和音频处理；[Gradio](https://github.com/gradio-app/gradio)，支持外部 TTS 客户端。
- [Bootstrap](https://github.com/twbs/bootstrap)、[Font Awesome](https://github.com/FortAwesome/Font-Awesome)、[Marked](https://github.com/markedjs/marked) 和 [DOMPurify](https://github.com/cure53/DOMPurify)，提供随应用打包的浏览器界面资源。其固定版本的源文件和许可证文件保留在 [app/static/vendor](app/static/vendor) 中。
- [Pinokio](https://pinokio.computer/)，提供安装和启动平台。
- 对于**可选的 Voice Tools**：感谢 [llama.cpp](https://github.com/ggml-org/llama.cpp)、[llama-cpp-python](https://github.com/abetlen/llama-cpp-python)、[OpenAI Whisper](https://github.com/openai/whisper)、[whisper.cpp](https://github.com/ggml-org/whisper.cpp)、[Silero VAD](https://github.com/snakers4/silero-vad) 和 [pyannote.audio](https://github.com/pyannote/pyannote-audio) 团队。这些工具支持本地 LLM 服务、语音转写、语音检测和可选的说话人分段识别；其安装及模型要求独立于核心工作流。

列入致谢不代表相关方为本项目背书。本节是对[许可证](LICENSE)、[第三方声明](THIRD_PARTY_NOTICES.md)以及各模型、数据集和依赖项条款的补充，不能替代这些文件和条款。

## 许可证

[MIT](LICENSE)。模型权重、数据集和外部服务各有其适用条款。

### 第三方许可证

随应用打包的运行时资源及其声明，请参阅 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

- [qwen_tts](https://github.com/QwenLM/Qwen3-TTS) — Apache License 2.0，版权所有：Alibaba Qwen Team
