<img src="icon.png" alt="Alexandriaのロゴ" width="160" />

# Side Story

*旧名：Alexandria Audiobook Nya*

本を複数の声で読むオーディオブックにします。AIによるスクリプトへの注釈付け、ローカルQwen3-TTS、ブラウザー編集を組み合わせ、人物に声を割り当て、聴き、行ごとに修正し、完成した本を書き出せます。

**[インストール](#installation) · [初めての作成](#quick-start) · [任意の音声ツール](#optional-tools) · [問題の切り分け](#troubleshooting) · [日本語ユーザーガイド](https://github.com/on22s/Side-Story/wiki/Home-ja-JP)**

[English](README.md) | [中文](README_CN.md) | 日本語

## できること

- **本を取り込む：** TXT、Markdown、EPUBから、話者と読み方の付いた編集可能なスクリプトを生成します。
- **声を割り当てる：** プリセット、参照音声のクローン、声のデザイン、LoRAを使えます。声やシリーズの配役を複数冊で再利用できます。
- **書き出し前に確認する：** チャンク（音声生成の単位）を試聴し、本文や話者を修正し、選んだ行だけ再生成できます。原文照合と声の検査もあります。
- **書き出す：** 結合MP3、章付きM4B、行／章ごとのファイル、Audacity用の話者別トラック。
- **実行先を選ぶ：** TTSはローカルまたは外部Qwen3-TTS Gradioサーバー。自動注釈はOpenAI互換のローカル／外部LLM、または手動コピー＆ペーストです。

まず **Setup → Script → Voices → Editor → Result** の5つの番号付きタブを使います。Designer、Dataset、Training、Preparer、Voice Lab、Reportsは必要時に使います。画面の英語ラベルは、この文書でもそのまま記載しています。

<a id="installation"></a>
## インストール

### Pinokio（推奨）

1. [Pinokio](https://pinokio.computer/)をインストールします。
2. **Download** に `https://github.com/on22s/Side-Story` を貼り付けます。
3. **Install**、完了後に **Start → Open Web UI** を選びます。
4. [初回手順](#quick-start)でLLMを接続し、短い音声を試します。

基本インストールはアプリとQwen3-TTS実行環境を含みます。TTS重みは初回使用時に取得し、LLM重みは別途用意します。**Install Voice Tools (Optional)** はネイティブPreparer/Voice Labと付属LLM起動用で、基本のオーディオブック作成には不要です。

新規環境はCPython 3.10の `app/env` を作り、OS別PyTorchを先に導入します。既存環境は保持されます。大きな本の前に[ハードウェアと初回の注意](#requirements)を確認します。

<a id="quick-start"></a>
## 最初のオーディオブック

**目標は、短い英語の地の文をRyanプリセットで読み、MP3を確認することです。** 本全体の前に[オリジナルの3文サンプル](docs/samples/first-audiobook.txt)を開き、**Download raw file** で保存するか、次の英文をUTF-8の `first-audiobook.txt` にコピーします。

> The rain stopped just before dawn. A small bird landed on the garden gate. By the time the kettle sang, the sky was bright.

サンプルはこのリポジトリのMITライセンスで提供するオリジナルで、会話がないため語り手だけで学べます。日本語版でも初回は同じ英語サンプルと言語設定を使います。

1. **Setup：** [LLM設定](https://github.com/on22s/Side-Story/wiki/LLM-Setup-ja-JP)で起動済みLLMに接続します。**Test Connection** の後に **Save Configuration** を押します。テストだけでは保存されません。**TTS Mode → Local Model (built in)**、**Device → Auto (best available)**、**TTS Language → English** を選び、**Runs on this machine's GPU?** を正しく設定して保存します。**確認：接続テストと設定保存が成功。**
2. **Script：** **Select Book/Novel (Text, Markdown, or EPUB)** でサンプルを選ぶと自動アップロードされます。任意の語り手欄は空のまま **Generate Annotated Script**。**確認：生成完了、3文保持、地の文の項目になっていること。チャンク数は変わる場合があります。**
3. **Voices：** 語り手カードで **Custom voice → Ryan**。キャラクタースタイルは空のまま **saved** を待ちます。**確認：Ryanが選択され未保存警告がないこと。**
4. **Editor：** 最初の行を **Gen** で生成して試聴し、よければ **Render Pending**。**確認：全行が再生可能で失敗／未完了がないこと。Text integrityは保存本文の照合で、実音声は検査しません。脱落や繰り返しも聴きます。**
5. **Editor → Result：** **Merge All** の原文照合確認を読み、意図しない差分があればキャンセルして直します。Resultで再生して **Download MP3**。**確認：取得ファイルが開き3文が順に全部入っていること。欠落／破損チャンクを飛ばして結合される場合があるためログも確認します。**

![5段階の手順図。アプリのスクリーンショットではありません（英語）](docs/images/first-audiobook-en.svg)

*図は操作順と確認点を示し、生成成功の証拠ではありません。各確認点は上に日本語で記載しています。*

**失敗したらその段階で止めてください。** 接続は[LLM設定](https://github.com/on22s/Side-Story/wiki/LLM-Setup-ja-JP)、初回TTS取得やエラーはPinokioの **Terminal** と[問題の切り分け](https://github.com/on22s/Side-Story/wiki/Troubleshooting-ja-JP)を確認します。最初は重み取得で長くかかる場合があります。

外部LLMには注釈用本文、外部TTSには生成入力が送られます。利用権限のある本と声を使います。**Save Currentは完全なバックアップではなく、Editorだけの編集、音声、出力を保持しません。** 切り替え前に[作業を保存](https://github.com/on22s/Side-Story/wiki/Updates-and-Backups-ja-JP)します。

### 最初のMP3の後に

- [初回の詳しい手順と回復](https://github.com/on22s/Side-Story/wiki/First-Audiobook-ja-JP)
- [手動LLMと他の接続先](https://github.com/on22s/Side-Story/wiki/LLM-Setup-ja-JP)
- [声、別名、ペルソナ、クローン、LoRA](https://github.com/on22s/Side-Story/wiki/Voices-ja-JP)
- [レビュー、チェックポイント、長い本](https://github.com/on22s/Side-Story/wiki/Scripts-and-Review-ja-JP)
- [M4B、章、Audacity](https://github.com/on22s/Side-Story/wiki/Rendering-and-Export-ja-JP)
- [Designer、Dataset、Training、Preparer、Voice Lab、Reports](https://github.com/on22s/Side-Story/wiki/Optional-Voice-Tools-ja-JP)

<details>
<summary>詳しい機能</summary>

## 注釈付けの機能

- OpenAI互換API（LM Studio、Ollama、OpenAIなど）のローカル／外部LLM。
- 分割・話者割り当て・読み方の3段階、編集可能なプロンプトプリセット、周辺文脈。
- 一時停止、スナップショット、失敗からの再開、複数冊処理。
- 接続プロファイル、タイムアウト、再試行、固有要求オプション、任意のfailover。
- 任意のLLMレビューと原文保持検査。
- LLMで人物説明を作りVoiceDesignで参照を生成、クローン声を自動割り当てするペルソナ生成。
- 声ライブラリーとシリーズ配役、時系列に沿うスタイル変更。
- `YOUNG ELENA` → `ELENA` のような別名による声設定共有。
- チャンク編集、話者一覧と周辺文脈の保持。

## 音声生成の機能

- ローカルQwen3-TTS、任意の外部Gradioサーバー。
- 英語、中国語、フランス語、ドイツ語、イタリア語、日本語、韓国語、ポルトガル語、ロシア語、スペイン語、自動判定。
- 読み方指示による感情／口調制御ができる9種類のCustomプリセット。
- 明瞭な参照と正確な書き起こしを使うクローン。取り込みは検証が必要です。
- 説明文からのVoice Design。
- 独自データによるBaseモデルのLoRA学習、声の同一性と読み方指示の組み合わせ。
- 付属LoRAカタログ。重みは必要時にHugging Faceから取得します。
- サンプルごとの本文、感情、試聴を持つDataset Builder。
- 可変バッチ数。**Compile Codec** は現在効果がありません（固定版のqwen-tts 0.1.1ではデコードがコンパイル対象外のため）。
- 原文の発声表現を本文として保持し、読み方を別に追加。
- 話者変更時500 ms、同話者250 msを初期値とする可変休止。

## ブラウザー編集と出力

5段階の基本UIと高度なツール、GPU／ディスク状態、診断、実行履歴、原文照合、声のずれ検査、行編集、選択再生成、小バッチ化、進捗ログ、単独／連続試聴、声設定付きスクリプトライブラリーがあります。

出力は結合MP3、DAW用の行別MP3、話者別WAVとLOF・ラベルを含むAudacity ZIP、題名／著者／語り手・表紙・章を含むAAC M4B、名前テンプレートと準備状態確認のある章別出力です。

</details>

<a id="requirements"></a>
## 必要な環境とハードウェア

実用的なローカルTTSにはGPUを推奨します。CPUも使えますが遅くなります。モデル、バッチ、LLMとの共有によりメモリーは変わり、万能な安全バッチ数はありません。モデル種類ごとに数GB、Python/PyTorch、LLM、本、音声にも容量が必要です。自動スクリプトには到達可能なOpenAI互換LLMが必要ですが、ローカルTTS自体に外部サーバーは不要です。

以下はインストーラーの経路で、すべてのGPU／ドライバーの保証ではありません。

| 環境 | ローカルTTS | 確認事項 |
| --- | --- | --- |
| Windows/LinuxのNVIDIA | PyTorch 2.7 / CUDA 12.8 | 対応GPUとドライバー、追加attention wheelのPython／OS互換性 |
| LinuxのAMD | PyTorch 2.10 / ROCm 7.0 | 明記された検証対象はRX 9070 XT / RDNA4。全AMD対応とは限りません。 |
| WindowsのAMD | CPU | このアプリの導入経路ではAMD GPU高速化を提供しません。 |
| Apple SiliconのmacOS | 利用可能ならMPS、そうでなければCPU | autoはPyTorchの判定を使います。全処理の互換性／速度保証ではありません。 |
| IntelのmacOS | CPU | 古いPyTorch固定版です。短いサンプルで確認します。 |
| その他CPUのみ | CPU | 遅い生成を想定し、短く始めます。 |

固定版は [torch.js](torch.js)、選択処理は [app/device_utils.py](app/device_utils.py) にあります。付属Docker ComposeはNVIDIA向けで、AMD導入手順ではありません。

<a id="optional-tools"></a>
## 任意のVoice Lab／Preparer

既存音声からのデータセット準備やネイティブVoice Lab処理には、停止後Pinokioの **Install Voice Tools (Optional)** を使います。CUDA/HIP/Metal/CPU用llama-cpp-python、独立 `preparer_env` とそのPyTorch制約、固定whisper.cppソース／モデルの検査とビルドを行います。pyannote 4の `torch>=2.8` を満たすLinux AMDだけに話者分離を導入します。他OSの `app/env` にpyannoteを追加しないでください。

CMake、C/C++ツールチェーン、GPU用SDK、追加容量が必要です。各ツールでモデル／Pythonパスを設定します。話者分離にはトークンと[Community-1の条件への同意](https://huggingface.co/pyannote/speaker-diarization-community-1)も必要です。基本の作成には不要です。

### CLIの準備と確認

追加ツール導入後、チェックアウト直下で実行します。Windowsでは `preparer_env/bin/python` を `preparer_env\Scripts\python.exe` に変更します。

- 対応EPUB/TXTと音声フォルダーを処理：
  `preparer_env/bin/python alexandria_batch_processor.py --folder /path/to/audio --source-folder /path/to/books --model /path/to/model.gguf`
- 抽出データの原文との比較・修正承認：
  `preparer_env/bin/python alexandria_compare.py --help`
- 基本環境の診断：`python env_doctor.py`。追加環境は `--voice-tools`、JSONは `--json`。
- オフライン用の旧Whisper-base Transformers取得：`preparer_env/bin/python download_model.py`。保存先は `models/whisper-base`。GGUF取得や現行whisper.cppの代わりではありません。

Linuxでは `bash run_with_restart.sh --audio /path/to/book.wav --source /path/to/book.epub --model /path/to/model.gguf --output /path/to/dataset.zip` が回数制限付き再試行とチェックポイント再開を行い、共有GPU lockを維持します。`preparer_env/bin/python` を優先し、変更には `ALEXANDRIA_PREPARER_PYTHON`、回数／遅延には `MAX_RETRIES`／`BACKOFF_SECONDS` を使います。

`corpus_alignment_prescan.py` は明示した組の初期照合、`corpus_run_report.py` は準備と検証済み出力receiptの報告用です。どちらも `--repo`、`--pairs`、`--output-dir`（help参照）を受け、新規reportには `--model`、任意で `--fallback` が必要です。pairsは `{ "audio": "/path/book.wav", "source": "/path/book.epub", "output_name": "book.zip" }` のJSON配列。Linux再起動wrapperと同じ追加環境が必要です。

DockerにはスクリプトはありますがネイティブVoice Toolsはありません。準備には別の環境を `ALEXANDRIA_PREPARER_PYTHON` で指定します。

### ローカルLLMの起動と診断

追加導入後、Pinokioの **Start LLM** は直下のGGUFを配信しローカル設定を更新します。重みは自動取得しません。Reset／Updateはサーバーを止めてから変更します。

別途導入済みLinuxネイティブ `llama-server` 用の `start_llama_server.sh` と `ensure_llama_server.sh` はモデル／アダプターの確認とlifecycle lockを保持します。`LLAMA_BIN`、`LLAMA_MODEL`、任意の `LLAMA_PORT`／`LLAMA_LOG` を設定します。バイナリー／モデルを導入するツールではありません。

アプリ環境を使う補助CLI：

- `app/env/bin/python app/analyze_generation_attempts.py --json`：保存された生成品質manifestを集計。
- `app/env/bin/python app/repair_source_llm.py --help`：原文修正提案。既定は報告のみですが設定LLMへ通信します。修正版の出力は `--apply` が必要。
- `app/env/bin/python app/tts_vram_benchmark.py --help`：Custom/CloneのGPUバッチ・codec計測。実測はモデルとGPU時間を使います。
- `app/env/bin/python tools/backfill_adapter_digests.py --root /path/to/adapters`：来歴digestの不足を監査。`--apply` なしはdry-runで、既存の不一致digestを上書きしたり過去学習の検証済みを主張したりしません。

Windowsは `app\env\Scripts\python.exe`、Dockerはこの4つのPython CLIに `python` を使います。ネイティブサーバーのシェル起動は準備済みLinux向けで、基本Docker向けではありません。

### Google Colab

[![Colabで開く](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/on22s/Side-Story/blob/main/alexandria_colab.ipynb)

付属ノートブックはColabに導入・起動し、Google Driveへの保存とColab内蔵のインラインポート転送を使います。ngrokアカウントは不要です。GPU利用可否とセッション制限はColabに依存し、詳細はノートブックを参照します。

### Docker（NVIDIA GPU）

[Docker](https://docs.docker.com/get-docker/)と[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)が必要です。

```bash
git clone https://github.com/on22s/Side-Story.git
cd Side-Story
docker compose up --build
```

`http://localhost:4200` を開きます。TTSは初回取得してDocker volumeに保持します。ユーザーデータはプロジェクトへのbind mountで保持します。標準イメージは基本実行環境のみで、ネイティブVoice Tools／preparer_envは含みません。

更新前に `data/` 全体を保存し、同じプロジェクトとモデルキャッシュを維持します。変更可能状態は `ALEXANDRIA_DATA_DIR=/alexandria/runtime` と `./data/runtime` に対応します。既存 `data/uploads`、`data/scripts`、`data/designed_voices`、`data/clone_voices`、`data/lora_models`、`data/lora_datasets`、`data/dataset_builder`、`data/output` はruntimeの対応位置にマウントし、ホストデータ移動は不要です。旧コンテナーパス `/alexandria/scripts`、`/alexandria/voicelines`、`/alexandria/app/uploads` はシンボリックリンクです。設定は `ALEXANDRIA_CONFIG_PATH=/alexandria/config/config.json` と `./data/config`。独自docker runでもruntimeとconfig両方を永続化します。

#### ネットワーク

Composeはホストの `127.0.0.1:4200` のみ公開し、コンテナー内は転送用 `0.0.0.0` です。認証は既定で無効です。公開・トンネル・リバースプロキシ利用前に `ALEXANDRIA_AUTH_PASSWORD`、必要なら `ALEXANDRIA_AUTH_USERNAME`（既定 `alexandria`）を設定します。信頼できるローカルネットワーク外はHTTPSを使います。

ドメインは `ALEXANDRIA_ALLOWED_HOSTS`、別ブラウザーオリジンは `CORS_ORIGINS`（正確なオリジン、カンマ区切り）を指定します。CORS_ORIGINSはCORSと要求オリジン検査の両方に使われ、`ALEXANDRIA_ALLOWED_ORIGINS` は検査だけを拡張します。認証の代わりにはなりません。イメージ／Composeへキーを埋め込まないでください。

## 初回起動

自動注釈用LLMを先に設定し、起動、モデルID、バックエンドからの到達性を確認します。Dockerのlocalhostはホストではありません。TTSは必要な重みをHugging Faceから取得するため、ターミナルで進捗を見ます。短い文章と小さいバッチで、読み込みやGPUウォームアップ後のメモリーを確認してから増やします。外部LLMには注釈／レビューの本文、外部TTSにはクローン参照と本文などが送られます。

## 更新とデータ

**Update** 前に保存・バックアップしてください。書き込み処理停止、コード取得、基本再導入を行いますが、中断回復は保証しません。任意依存が変われば停止後にVoice Toolsを再導入します。

通常の配置では `app/config.json`、作業中JSON、`app/uploads/`、`scripts/`、`voicelines/`、出力、声ライブラリー、データセット、アダプター、関連チェックポイントを保持します。カスタムデータ／設定先も含めます。[詳細な保存一覧](https://github.com/on22s/Side-Story/wiki/Updates-and-Backups-ja-JP)を参照してください。

**Resetは作業中スクリプト、チャンク、現在の声設定／状態、行音声、結合MP3、既定設定を削除します。** 再利用ライブラリーは保持しますが完全な作業バックアップにはなりません。Resetの削除対象はチェックアウト内の既定パスです。独自のデータ／設定ディレクトリーまで消去されるとは限りません。一般的な修復として使わないでください。

<details>
<summary>タブごとの使い方</summary>

## Setup

LLMとTTSを設定します。TTSの **Mode** はlocal/external、**Device** はまずautoです。UIはCUDAとCPU、バックエンドは利用可能なMPSも受け付けます。**Language** は上記10言語／Auto、既定はEnglishです。

**Parallel Workers** は外側ローカルバッチまたはサーバーごとの外部並列数。**Auto-configure** は12〜20 GBのGPUで4を設定します（RX 9070 XTの実測で2より約23%速く、Whisper再現率は同等、試聴確認済み）。**Batch Seed** はローカルCustom/Clone/LoRA用で全経路への上書きではありません。**Compile Codec** は現在効果がないため無効のままにします。**Sub-batching** は初期状態で有効で長さ別に分けpaddingの無駄を減らします。**Max Items/Batch** は上限、0はVRAM推定。長さ別分割が無効でもメモリー／手動上限は適用されます。**Min Sub-batch Size** は初期4、**Length Ratio** は初期5。休止は話者変更500 ms、同話者250 msです。

高度な設定はchunk size、回答max tokens、Temperature、Top P、Top K、Min P、Presence Penalty、カンマ区切り **Banned Tokens**、段階別プロンプトとレビュー／ペルソナです。禁止トークンは万能な推論停止ではありません。[プロンプト編集](#prompt-customization)後は保存します。**Step 1: model output format** は *Full text*（既定）か *Compact labels*（試験的）。後者は番号付きの文にラベルだけを返させ、使えない回答のチャンクは全文方式に戻ります（引用符で決まらないチャンクのみ）。**Step 3: extra text around each request** は読み方指示の要求に加える読み取り専用の前後文（片側0〜1,000,000文字、既定0）。Step 3は同じ要求内の行を重複送信しなくなりました。4,000文字で品質向上は測定されなかったため、試験以外は0のままにします。20,000文字を超える値にはモデルのcontext長が必要です。

## Script

TXT/MD/EPUBを取り込みます。EPUBはアップロード時にテキストへ変換します。LLMはNARRATOR／人物の識別、原文の発声表現を含む本文保持、読み方をJSONにします。**Review Script** は話者・地の文／会話・指示を再確認します。連続する語り手の結合は任意で既定無効です。人の点検が必要です。レビュー開始時にGPUメモリーが既に満杯なら、再試行せずすぐ停止してメッセージを表示します。メモリーを空けて（例：保持しているモデルをアンロード）から再開します。Setup の **Attribution prompt** で話者の尋ね方を選べます。既定は `michel2_full` で、会話行だけを尋ねる `michel2_spoken` は Qwen3-14B（アダプターなし）で 6.5 ポイント高く、第 2 段階も約 3 倍速くなりました（他のモデルは未測定、アダプターは学習時のプロンプトのまま）。任意のラベル専用レビュー（`prompts.review_labels_only`）は本文を書き直さず話者と指示だけを返します。モデルの応答は `logs/llm_responses.log`、そのリクエストは `logs/llm_responses.requests.log` に記録されます。各設定の横の ⓘ で説明が見られます。詳細は[スクリプトとレビュー](https://github.com/on22s/Side-Story/wiki/Scripts-and-Review-ja-JP)。

**Preserve source words**（生成前のチェックボックス）は原文の語を順番どおり注釈とレビューで保持し、語が変わったスクリプトの公開やチャンクの音声化を拒否します。数字や記号の読み上げ展開は後の音声準備で行われます。既定は無効です。[Literal source policy（英語）](docs/literal_source_policy.md)を参照してください。

**Speaker-label suggestions** は停止中のスナップショットと保存済み暫定参照を比較し、回数制限付きモデル判断を確認して別名を1件ずつ明示適用できます。[公開ガイド（英語）](docs/speaker-label-review.md)と[日本語wiki](https://github.com/on22s/Side-Story/wiki/Scripts-and-Review-ja-JP)を参照してください。レビューの既定プロンプトはreview_prompts.txtで、本文保持の実行時検証は編集後も働きます。

## Voices

スクリプトから話者を読み込みます。**Generate Personas** は人物説明・サンプルからVoiceDesign参照を作り、クローンを割り当てます。Standardは選択話者を逐次、Advancedはスクリプト発見バッチ（初期40項目）を制御し、**Apply to** で未割り当て／再生成対象を指定します。先に対象を確認し、生成後は参照を聴きます。

**Alias of** は名前・年齢表記の違いに声を共有し、A → B → CならCの設定を使い循環検知します。Customは9プリセットと持続スタイル・行の指示、任意seed。Cloneは参照と正確な本文を使い、通常instructは無視します。LoRAはTrainingのアダプターとスタイル・行の指示。Voice Designは説明と行の指示から都度ローカル生成します。

## Designer、Training、Dataset

Designerは自然言語の説明とサンプルで試聴し、ライブラリーへクローン参照として保存します。TrainingはBaseモデルのLoRA学習と、別途重み取得するプリセット一覧です。データは24 kHzモノラルWAVと `audio_filepath`／`text` を持つ `metadata.jsonl` のZIP、または **Build New Dataset** で作成します。名前、epoch、学習率、rank/alpha、言語、バッチ、勾配蓄積を環境に合わせ、学習未使用の行で試します。rank／epochを増やせば必ず改善するわけではありません。

Datasetは声説明と任意seedでプロジェクトを作り、各行の本文・感情を設定し、個別／一括試聴します。一括キャンセルは完了サンプルを保持します。学習用へ保存するとTrainingに表示されます。VoiceDesignで音声を作ります。

## Editor、音声生成、Result

Editorは状態付き行一覧、話者・本文・instruct編集、行ごとの生成、pending生成、連続試聴、結合です。Render Pendingが方式を自動選択し、ローカルはCustom/Clone/LoRAをバッチ、Voice Design／ensembleを逐次、外部は並列要求で処理します。別のStandard／Batch (Fast)ボタンはありません。Parallel WorkersとMax Items/Batchを調整し、短く試します。

ResultはMP3、章マーカー付きAAC M4B、話者別Audacity WAVを取得します。M4Bは見出し検出、**Per-chunk chapters** は各行を章にします。Audacityは展開後project.lofを開き **File → Import → Labels** からlabels.txtを読みます。一部Linuxプレーヤー（Cozyなど）はM4B対応が限られます。英語READMEにはVLC、Haruna、Audiobookshelfでの確認が記載されていますが、この翻訳では再試験していません。

</details>

## 性能とGPU調整

小さいバッチから自分の環境で計測します。**Auto-configure** がGPUに合うバッチ数を選びます。Compile Codecは現在効果がないため無効のままにします。メモリー不足後はParallel Workers／Max Items/Batchを下げ、共有LLMにも余裕を残します。AMD/Linuxは実GPU／ROCmを確認し、他人の電力設定やPyTorch変更を無条件にコピーしません。`app/tts_vram_benchmark.py --help` の実測はモデルとGPU時間を消費します。速度の保証値はありません。

<details>
<summary>スクリプト形式、出力ファイル、API</summary>

## スクリプト形式

`speaker`、`text`、`instruct` を持つJSON配列です。英文例の値はそのまま示します。

```json
[
  {"speaker": "NARRATOR", "text": "The door creaked open slowly.", "instruct": "Calm, even narration."},
  {"speaker": "ELENA", "text": "Ah! Who's there?", "instruct": "Startled and fearful, sharp whispered question, voice cracking with panic."},
  {"speaker": "MARCUS", "text": "Haha... did you miss me?", "instruct": "Menacing confidence, low smug drawl with a dark chuckle, savoring the moment."}
]
```

instructは口調と読み方の短い指示です。既定のdelivery段階は概ね8～15語の1～2文を求めます。3段階処理は原文の言葉を保持して読み方を別に追加する設計ですが、完全な忠実性の保証ではありません。生成前／結合前にスクリプトと原文照合を点検します。

## 出力

`ALEXANDRIA_DATA_DIR` は変更可能状態、`ALEXANDRIA_CONFIG_PATH` は設定の場所を指定します。Dockerのデータルートは `/alexandria/runtime` です。

- `cloned_audiobook.mp3`：休止を含む結合音声。
- `voicelines/voiceline_<uid>_narrator.mp3` など：一意チャンクIDと話者の行音声。MP3失敗ならWAV。時系列はファイル名順ではなくEditor／メタデータで確認します。
- `audacity_export.zip`：project.lof、labels.txt、narrator.wav／elena.wav／marcus.wavなど。全トラックを同じ長さに無音で埋め、同時再生で時系列を再構成します。
- `audiobook.m4b`：AACと埋め込み章。見出し自動検出またはチャンクごとの章。対応プレーヤーを使います。

## API

起動ツールのBase URLを使います。Pinokioは空きポート、直接 `python app.py` は `ALEXANDRIA_PORT` 指定がなければ `http://127.0.0.1:4200`。スキーマは `<BASE>/docs`、JSONは `<BASE>/openapi.json` です。パスワード設定時はHTTP Basicが必要です。ユーザーは既定alexandria、ALEXANDRIA_AUTH_USERNAMEで変更します。ブラウザーは許可されたoriginを使い、最も簡単なのは同一originです。HTTPコードを確認します。開始成功は完了ではありません。

### 設定とスクリプト

- `GET /api/config`：キーを伏せた設定。
- `GET /api/default_prompts`：生成段階、レビュー、ペルソナの既定。
- `POST /api/config`：`llm`、`tts`、`llm_mode` に一致する有効 `llm_local`／`llm_remote` を含めて保存。詳細はschema。
- `POST /api/upload`：multipart `file`、txt/md/epub。既定でそのソースを選択。
- `POST /api/generate_script`：選択ソースの開始／再開。任意JSONは `strip_front_matter`、`first_person_narrator`、`start_over`。
- `GET /api/annotated_script`：現在のスクリプト。
- `POST /api/review_script`：レビュー開始。
- `GET /api/scripts`、`POST /api/scripts/save`、`POST /api/scripts/load`：一覧、保存、読み込み。後者2つは `{"name":"my-novel"}`。

### 声と音声

- `GET /api/voices`：話者と声設定。
- `POST /api/save_voice_config`：話者をキーに更新。例 `{"NARRATOR":{"type":"custom","voice":"Ryan","character_style":"calm"}}`。
- `POST /api/generate_personas`：生成開始。taskは `persona`。
- `GET /api/chunks`：状態／音声パス付きの順序付き配列。
- `POST /api/chunks/{index}`：更新。`POST /api/chunks/{index}/generate`：生成。
- `POST /api/generate_batch`／`POST /api/generate_batch_fast`：`{"indices":[0,1,2]}` のような0始まり配列位置。チャンクIDではありません。
- `GET /api/editor/integrity`：原文照合。
- `POST /api/merge`：MP3結合開始。検証済みでない報告は確認が必要で、確認不足／古いsnapshotはHTTP 409です。報告を読んで `snapshot` を `integrity_confirmation` として明示承認します。
- `GET /api/audiobook`：完了後MP3取得。
- `POST /api/export_audacity`：開始、`GET /api/export_audacity`：ZIP取得。
- `POST /api/merge_m4b`：JSON設定で開始、`GET /api/audiobook_m4b`：取得。

### タスク状態

`GET /api/status` で登録task名、`GET /api/status/{task_name}` でrunning、ログ、固有結果を確認します。

| 操作 | task名 |
| --- | --- |
| スクリプト生成 | `script` |
| レビュー | `review` |
| ペルソナ | `persona` |
| 行音声とMP3結合 | `audio` |
| Audacity／M4B | `audacity_export`／`m4b_export` |
| LoRA学習 | `lora_training` |

開始は通常 `{"status":"started"}` でtask IDではありません。汎用completed/error欄はなく、`running: false` は停止だけを示します。ログと固有結果を確認します。

クライアントの順序は、upload → generate → 終了結果確認 → 任意reviewと確認 → 声設定 → render → 全必要行doneの確認 → integrity確認 → merge → 終了ログ確認 → downloadです。Audacityは `result.status`（done/failed/cancelled）もあります。Designer、Dataset、学習、キャンセル、高度な要求は現行 `/docs` を参照します。

</details>

## LLMの選択

構造化出力の指示に従うモデルを短く試します。品質、文脈上限、メモリーはモデルにより異なります。LM Studio、Ollama互換API、対応外部APIをSetupで設定します。思考ばかり出す場合は提供元の対応非推論設定を使います。禁止トークンだけで推論を止める万能手段はありません。手動方式は長い本では操作が増えます。

<a id="troubleshooting"></a>
## トラブルシューティング

- **スクリプト失敗：** 起動、到達性、正確なモデル名を確認し、JSONが苦手なら別のモデルを短く試します。
- **重み取得失敗／遅い：** TTSはモデルごと約3.5 GBで初回Hugging Faceから取得します。英語版はネットワーク制限時の例として `HF_ENDPOINT=https://hf-mirror.com`、Pinokioのstart.jsの `env: { HF_ENDPOINT: "https://hf-mirror.com" }` を記載しています。ミラーは信頼先を変更するため自分で確認し、信頼できない先へトークンを送らないでください。レート制限には[Hugging Face](https://huggingface.co/join)の許可されたHF_TOKENを使えます。中断取得はアプリ再起動で再開できます。
- **TTS失敗：** ターミナルの最初のモデル／生成エラー、空きメモリー、バッチ上限、外部Gradio起動とURL、voice_config.json、参照音声と正確な本文を確認します。
- **バッチが遅い：** SetupでAuto-configureを実行するか、VRAMがあればParallel Workersを上げます。Compile Codecは現在効果がありません。Render Pendingは自動バッチです。AMDは実エラーとROCm/PyTorchを調べ、MIOpen警告をすべて同じ原因と扱いません。
- **メモリー不足：** Parallel Workersを下げ、他GPU処理を閉じ、必要なら遅い `device: cpu` を試します。
- **428 bytesなどの小さい／破損MP3：** FFmpegのlibmp3lame不足なら行出力はWAVになり得ますが、結合にはMP3 encoderが必要です。英語版の修復例は `conda install -c conda-forge ffmpeg`、またはシステム版を使うための `conda remove ffmpeg`。実際の環境と使用実体を確認して選びます。検査は `ffmpeg -encoders 2>/dev/null | grep mp3`（POSIX）、Windowsは `ffmpeg -encoders`。
- **音声品質：** ノイズのない正確な参照。取り込みは3～30秒・品質検査・権利確認。Customの別seedも試します。
- **文字化け：** 既知の問題は原本を変えずメモリー内で修復する場合があります。未解決は報告され、入力UTF-8を確認します。

詳しくは[日本語wiki](https://github.com/on22s/Side-Story/wiki/Troubleshooting-ja-JP)を参照します。

<a id="prompt-customization"></a>
## プロンプト編集

**Setup → Prompt Settings (Advanced)** に分割（Step 1）、話者（Step 2）、読み方（Step 3）、レビュー、ペルソナの別プリセットがあります。**What the model will see** で話者要求を確認します。**Save Configuration** または **Save preset and Setup** で保存します。**Reset to Defaults** は欄を置き換え、保存して初めて保持されます。

既定の取得元：

- [app/default_prompts_segment.txt](app/default_prompts_segment.txt)：分割。
- [app/default_prompts_instruct.txt](app/default_prompts_instruct.txt)：読み方。
- [app/attribution_prompt_variants.py](app/attribution_prompt_variants.py)、[app/default_prompts_attribute.txt](app/default_prompts_attribute.txt)：話者のバリアントと既定形式。
- [review_prompts.txt](review_prompts.txt)、[persona_prompts.txt](persona_prompts.txt)：レビューとペルソナ。

直下default_prompts.txtは旧1段階生成用で、それだけ編集しても現行3段階は変更できません。英語以外は言語固有の会話表記を考慮し、TTS Languageも合わせます。

<details>
<summary>プロジェクト構成</summary>

## プロジェクト構成

```
Alexandria/
├── app/
│   ├── app.py                 # FastAPIと起動
│   ├── routers/               # APIルート
│   ├── core.py                # 共通設定・タスク・実行状態
│   ├── tts.py                 # ローカル／外部TTS
│   ├── train_lora.py          # LoRA学習子プロセス
│   ├── generate_script.py     # 旧1段階注釈
│   ├── generate_personas.py   # ペルソナとVoiceDesign割り当て
│   ├── review_script.py       # LLMレビュー
│   ├── utils.py               # 共通処理・原子的JSON保存
│   ├── default_prompts.py     # 生成段階のプロンプト読み込み
│   ├── review_prompts.py      # レビュープロンプト読み込み
│   ├── project.py             # チャンク管理とバッチ生成
│   ├── parse_voices.py        # 話者抽出
│   ├── config.json            # 実行設定（Git対象外）
│   ├── static/index.html      # Web UI
│   └── requirements.txt       # Python依存関係
├── builtin_lora/              # プリセット一覧と取得済みLoRA
├── dataset_builder/           # データセット作業領域（Git対象外）
├── designed_voices/           # Designerの出力（Git対象外）
├── lora_datasets/             # 学習データ（Git対象外）
├── lora_models/               # LoRAアダプター（Git対象外）
├── default_prompts.txt        # 生成プロンプト
├── review_prompts.txt         # レビュープロンプト
├── install.js                 # 基本Pinokio導入
├── install-voice-tools.js      # 任意ネイティブツール導入
├── tools/voice_lab/            # 音声処理補助
├── data/                      # Dockerマウント（Git対象外）
├── start.js                   # Pinokio起動
├── reset.js                   # リセット
├── pinokio.js                 # Pinokio UI設定
├── pinokio.json               # Pinokio情報
└── README.md
```

</details>


## 謝辞

Side Storyは多くの人の成果、アイデア、不具合報告、試験に支えられています。元のAlexandriaコミュニティと各フォークの改善に協力した皆さんに感謝します。

### アプリ、貢献、試験

- 元のAlexandria Audiobookアプリと、ダウンロードできるAlexandria音声プリセット。 [Finrandojin](https://github.com/Finrandojin/alexandria-audiobook) · [Alexandria voice presets](https://huggingface.co/Finrandojin/Alexandria)
- ペルソナ生成、話者別名の解決、文脈付きスクリプトレビュー。関連プロジェクトはLilyです。 [Ayush Naphade](https://github.com/aayushnaphade) · [upstream PR #42](https://github.com/Finrandojin/alexandria-audiobook/pull/42) · [Lily](https://lily.rayoneai.in/)
- Alexandria Audiobook2からNyaに継承した改善。上流のSystem Health Dashboard、OSをまたぐサブプロセス実行、Voice Training Dataset Preparerなど。 [Michii / on22s](https://github.com/on22s) · [Alexandria Audiobook2](https://github.com/on22s/alexandria-audiobook2) · [#45](https://github.com/Finrandojin/alexandria-audiobook/pull/45) · [#46](https://github.com/Finrandojin/alexandria-audiobook/pull/46) · [#47](https://github.com/Finrandojin/alexandria-audiobook/pull/47)
- 手動LLM方式、スナップショット、ペルソナの段階更新、プロンプト編集、人物状態別の声を形作った詳細提案・再現例・継続的な試験。 [REFLEXGAMING007](https://github.com/REFLEXGAMING007) · [manual generation](https://github.com/on22s/alexandria-audiobook2/issues/593) · [snapshots](https://github.com/on22s/alexandria-audiobook2/issues/600) · [incremental updates](https://github.com/on22s/alexandria-audiobook2/issues/602) · [prompt editing](https://github.com/on22s/alexandria-audiobook2/issues/634) · [state personas](https://github.com/on22s/alexandria-audiobook2/issues/866)

- 上流に統合された初期Web UI、Audio Editor、チャンク管理。 [Alchemist-Production](https://github.com/Alchemist-Production) · [integration](https://github.com/Finrandojin/alexandria-audiobook/commit/1667edc237418fbf9e819bfb4294b14209da9c27) · [editor](https://github.com/Finrandojin/alexandria-audiobook/commit/717f89161b36ced57c97cea5b729be95b3cba39e)
- on22sが上流へ取り込んだHTMLエスケープによるセキュリティ改善。 [PierrunoYT](https://github.com/PierrunoYT) · [upstream PR #39](https://github.com/Finrandojin/alexandria-audiobook/pull/39)
- 外部TTSのimport不足修正。kishore-1404によるCUDAのVRAM属性修正にも感謝します。 [Robertoge65](https://github.com/Robertoge65) · [upstream PR #19](https://github.com/Finrandojin/alexandria-audiobook/pull/19) · [kishore-1404](https://github.com/kishore-1404) · [upstream PR #35](https://github.com/Finrandojin/alexandria-audiobook/pull/35)
- 後の上流Docker更新に取り込まれたペルソナプロンプトの梱包修正。 [MNeMoNiCuZ](https://github.com/MNeMoNiCuZ) · [original contribution and credit](https://github.com/Finrandojin/alexandria-audiobook/pull/56#issuecomment-5044676266)

<details>
<summary>継承した修正を支えた報告・アイデア・試験</summary>

- 初期のWindows／音声フィードバック、ダウンロードとCPU読み込みの報告。 [ElBiggus](https://github.com/ElBiggus) · [download](https://github.com/Finrandojin/alexandria-audiobook/pull/5#issuecomment-3870041305) · [CPU-loading](https://github.com/Finrandojin/alexandria-audiobook/issues/4)
- バッチ生成とキャンセル試験、古いクローンプロンプトキャッシュの原因特定と修正確認。 [1BadAshB](https://github.com/1BadAshB) · [stale clone-prompt cache diagnosis](https://github.com/Finrandojin/alexandria-audiobook/issues/17#issuecomment-3940188658)
- モデルキャッシュ読み込みとNVIDIAでの低速化の報告・試験。 [generallogin](https://github.com/generallogin) · [model-cache loading](https://github.com/Finrandojin/alexandria-audiobook/issues/22) · [NVIDIA slowdown](https://github.com/Finrandojin/alexandria-audiobook/issues/23)
- 学習／推論のprefill修正を特定・確認する助けになった韓国語LoRA試験。 [ryuhda](https://github.com/ryuhda) · [training/inference prefill fix](https://github.com/Finrandojin/alexandria-audiobook/issues/29#issuecomment-4315574687)
- 安全な項目フィルタリングにつながった不正LLM出力の報告。 [sdbrown67](https://github.com/sdbrown67) · [malformed LLM-output report](https://github.com/Finrandojin/alexandria-audiobook/issues/20#issuecomment-3985423529)
- 言語設定と編集可能レビュープロンプトを改善する助けになったドイツ語とプロンプトの意見。 [WirelessRoth](https://github.com/WirelessRoth) · [German-language and prompt feedback](https://github.com/Finrandojin/alexandria-audiobook/issues/13)
- Dockerの起動、設定、VRAM解放の報告。 [damajor](https://github.com/damajor) · [Docker startup, configuration, and VRAM-cleanup reports](https://github.com/Finrandojin/alexandria-audiobook/issues/62#issuecomment-5044680044)
- 上流で採用されたDrive優先保存とngrokを使わないColabの提案。 [futuregadets](https://github.com/futuregadets) · [Drive-first storage](https://github.com/Finrandojin/alexandria-audiobook/issues/59) · [ngrok-free Colab](https://github.com/Finrandojin/alexandria-audiobook/issues/60)
- 外部音声クローンの言語に関する報告。 [Tortoise17](https://github.com/Tortoise17) · [external voice-clone language report](https://github.com/Finrandojin/alexandria-audiobook/issues/69#issuecomment-5062433885)
- 目次に基づく章見出し回復につながった画像形式EPUB見出しの議論。 [starpause](https://github.com/starpause) · [image-based EPUB chapter-heading discussion](https://github.com/Finrandojin/alexandria-audiobook/issues/80#issuecomment-5309266456) · [AA2 implementation](https://github.com/on22s/alexandria-audiobook2/pull/314)

</details>

### 継承した改善とアイデア

- Nyaのfp32モデル読み込み経路に参考となったAMD APUの精度修正。 [cjdell](https://github.com/cjdell/alexandria-audiobook) · [port](https://github.com/on22s/alexandria-audiobook2/pull/573)
- OpenAI推論モデルの要求処理、環境変数参照APIキー、推論設定、参照検証、外部TTSプール、更新する物語文脈のアイデア。 [XinchaoGou](https://github.com/XinchaoGou/alexandria-audiobook) · [ports](https://github.com/on22s/alexandria-audiobook2/pull/574) · [reasoning controls](https://github.com/on22s/alexandria-audiobook2/pull/530) · [reference validation](https://github.com/on22s/alexandria-audiobook2/pull/531) · [server pools](https://github.com/on22s/alexandria-audiobook2/pull/532)
- MP3ビットレートの知見と、キャンセル可能な結合、出力進捗、モデル選択、タブ記憶のアイデア。AA2で独立に実装されNyaへ継承されました。 [Darkkingwill](https://github.com/Darkkingwill/alexandria-audiobook) · [bitrate](https://github.com/on22s/alexandria-audiobook2/pull/533) · [interface improvements](https://github.com/on22s/alexandria-audiobook2/pull/534)
- TTS生成トークン上限の設定というアイデア。対応するメモリー推定とともに実装されました。 [shangyuok](https://github.com/shangyuok/alexandria-audiobook-gg) · [implementation](https://github.com/on22s/alexandria-audiobook2/pull/60)
- 本をまたぐ配役記憶と生成音声の一貫性確認のアイデア。Alexandriaで独立に実装されました。 [dudarenok-maker / Castwright](https://github.com/dudarenok-maker/Castwright) · [series memory](https://github.com/on22s/alexandria-audiobook2/pull/524) · [voice checks](https://github.com/on22s/alexandria-audiobook2/pull/525)
- 引用の話者割り当て研究。michelプロンプト群としてAlexandria独自のプロンプトと周辺文脈処理へ適応しました。 [Gaspard Michel, Elena V. Epure, Romain Hennequin, and Christophe Cerisara](https://aclanthology.org/2025.naacl-short.62/) · [implementation](app/attribution_prompt_variants.py)

<details>
<summary>研究上の影響と共有資料</summary>

NyaはAA2の研究からも知見を得ています。以下は実験や評価資料への謝辞で、すべての実験・データセット・モデルがNyaの実行環境に含まれるという意味ではありません。

- 行ごとの指示語彙と、安定した声の特徴を読み方から分ける実験。語彙はAA2研究ツールに移植され、比較結果が声の同一性の改善に役立ちました。 [Xiao Zhang / buddies](https://github.com/buddies/alexandria-audiobook) · [audit](https://github.com/on22s/alexandria-audiobook2/pull/601) · [voice changes](https://github.com/on22s/alexandria-audiobook2/pull/603)
- AA2の引用を考慮した分割実験に取り入れた句読点の優先順位。 [p0n1](https://github.com/p0n1/epub_to_audiobook)
- AA2で検討した、音声の再書き起こしによる検証と途中切れ検出のアイデア。 [zeropointnine](https://github.com/zeropointnine/tts-audiobook-tool)
- 話者比較のきっかけとなったBookNLPベースライン。David BammanとBookNLP貢献者の文学NLP研究にも感謝します。 [Drew Thomasson / VoxNovel](https://github.com/DrewThomasson/VoxNovel) · [David Bamman and the BookNLP contributors](https://github.com/booknlp/booknlp)
- AA2で検討した重み付き声混合。WhiskeyCoderの独立したQwen3-TTSチャンク長の知見も比較に使われました。 [nazdridoy](https://github.com/nazdridoy/kokoro-tts) · [WhiskeyCoder](https://github.com/WhiskeyCoder/Qwen3-Audiobook-Converter)
- PDNC注釈者、RiQuAのSean PapayとSebastian Padó、DraCorコミュニティによる、AA2話者研究で使った注釈付き文学資料。 [Krishnapriya Vishnubhotla, Adam Hammond, and Graeme Hirst](https://aclanthology.org/2022.lrec-1.628/) · [Sean Papay and Sebastian Padó](https://aclanthology.org/2020.lrec-1.104/) · [DraCor](https://dracor.org/)
- AA2の構文フレーム実験で検討した引用話者の分類。Frank RudziczらBookNLP-OG共著者によるエンドツーエンドの話者割り当て比較にも感謝します。 [David K. Elson and Kathleen R. McKeown](https://www.cs.columbia.edu/~delson/pubs/AAAI10-ElsonMcKeown.pdf) · [Frank Rudzicz and the BookNLP-OG coauthors](https://arxiv.org/abs/2307.03734)
- AA2で調べた音声モデル設計のアイデア。CosyVoiceはNyaの実行時依存関係ではありません。 [CosyVoice team](https://github.com/QwenAudio/CosyVoice)
- LibriVoxの読み手、Project Gutenbergと青空文庫のボランティア、LJSpeech、Hi-Fi TTS、AISHELL-3、Kokoro Speech Dataset制作者による、研究比較の人の朗読と原文。 [LibriVox](https://librivox.org/) · [Project Gutenberg](https://www.gutenberg.org/) · [Aozora Bunko](https://www.aozora.gr.jp/) · [LJSpeech](https://keithito.com/LJ-Speech-Dataset/) · [Hi-Fi TTS](https://www.openslr.org/109/) · [AISHELL-3](https://www.openslr.org/93/) · [Kokoro Speech Dataset](https://mozilladatacollective.com/datasets/cmmknsho4014wmf087kvq5rc6)
- 同じ場面の人物同士の声の対比と、一貫した人物の声についての実務的な考え方。第三者通知にも配役の参考資料を記録しています。 [Jay Myers](https://www.jaymyersvoiceover.com/blog-ideas/how-audiobook-narrators-make-characters-sound-distinct-believable-and-consistent) · [Malk Williams](https://www.linkedin.com/pulse/character-voices-audiobooks-7-key-considerations-malk-williams) · [Third-Party Notices](THIRD_PARTY_NOTICES.md#research-and-industry-practice-consulted)

参考研究、適応した内容、資料ごとの権利上の注意は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) に記録しています。

</details>

### モデルとツール

次のプロジェクトの保守者と貢献者に感謝します。

- ローカル音声生成、クローン、Voice Designを支えるQwen3-TTS。Alibaba Qwenチームに感謝します。 [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)
- モデル実行とアダプター学習。SpeechBrainは声の検査用の話者埋め込みを提供します。 [PyTorch](https://pytorch.org/) · [Hugging Face Transformers](https://github.com/huggingface/transformers) · [PEFT](https://github.com/huggingface/peft) · [SpeechBrain](https://github.com/speechbrain/speechbrain)
- アプリ配信と音声処理を支えるFastAPI、pydub、SoundFile、librosa、FFmpeg。Gradioは外部TTSクライアントに使います。 [FastAPI](https://github.com/fastapi/fastapi) · [pydub](https://github.com/jiaaro/pydub) · [SoundFile](https://github.com/bastibe/python-soundfile) · [librosa](https://github.com/librosa/librosa) · [FFmpeg](https://ffmpeg.org/) · [Gradio](https://github.com/gradio-app/gradio)
- 付属ブラウザーUIの資産。固定版の取得元とライセンスをapp/static/vendorに保持しています。 [Bootstrap](https://github.com/twbs/bootstrap) · [Font Awesome](https://github.com/FortAwesome/Font-Awesome) · [Marked](https://github.com/markedjs/marked) · [DOMPurify](https://github.com/cure53/DOMPurify) · [app/static/vendor](app/static/vendor)
- インストールと起動の基盤。 [Pinokio](https://pinokio.computer/)
- 任意のVoice Toolsを支えるllama.cpp、llama-cpp-python、Whisper、whisper.cpp、Silero VAD、pyannote.audio。ローカルLLM配信、書き起こし、発話検出、任意の話者分離に使い、基本手順とは別の導入・モデル要件があります。 [llama.cpp](https://github.com/ggml-org/llama.cpp) · [llama-cpp-python](https://github.com/abetlen/llama-cpp-python) · [OpenAI Whisper](https://github.com/openai/whisper) · [whisper.cpp](https://github.com/ggml-org/whisper.cpp) · [Silero VAD](https://github.com/snakers4/silero-vad) · [pyannote.audio](https://github.com/pyannote/pyannote-audio)

謝辞は支持や推奨を意味しません。[ライセンス](LICENSE)、[第三者通知](THIRD_PARTY_NOTICES.md)、各モデル・データセット・依存関係の利用条件を補足し、置き換えるものではありません。


## ライセンス

[MIT](LICENSE)。モデル重み、データセット、外部サービスはそれぞれの条件に従います。

### 第三者ライセンス

同梱資産と通知は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。

- [qwen_tts](https://github.com/QwenLM/Qwen3-TTS)：Apache License 2.0、Copyright Alibaba Qwen Team。

日本語版は公開main `840d08cd20306f347950c6cd25deadf3bd69b654` のREADMEと公開wikiを参照しています。翻訳作業ではインストールやGPU生成の実行試験を行っていません。
