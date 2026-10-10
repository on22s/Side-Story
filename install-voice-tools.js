// Optional native dependencies for Voice Lab and the isolated Preparer.
// The base audiobook app does not need these builds or the Whisper download.
// Diarization is provisioned only for Linux AMD: its torch pin satisfies
// pyannote.audio 4's torch>=2.8 requirement; other torch.js pins do not.
const whisperAssets = require("./whisper_assets.json")

module.exports = {
  "requires": {
    "bundle": "ai"
  },
  "run": [
    {
      "when": "{{!exists('app/env')}}",
      "method": "script.start",
      "params": {
        "uri": "install.js"
      }
    },
    {
      "method": "script.start",
      "params": {
        "uri": "llama_cpp.js",
        "params": {
          "path": "app",
          "venv": "env",
          "constraints": "torch-constraints.txt"
        }
      }
    },
    {
      "when": "{{!exists('preparer_env')}}",
      "method": "shell.run",
      "params": {
        "message": "uv venv --python 3.10 preparer_env"
      }
    },
    {
      "method": "script.start",
      "params": {
        "uri": "torch.js",
        "params": {
          "path": ".",
          "venv": "preparer_env"
        }
      }
    },
    {
      "method": "shell.run",
      "params": {
        "venv": "preparer_env",
        "message": "python -c \"import importlib.metadata as m, pathlib; wanted={'torch','torchvision','torchaudio','pytorch-triton','pytorch-triton-rocm','triton-rocm'}; rows=[f'{d.metadata[\\\"Name\\\"]}=={d.version}' for d in m.distributions() if d.metadata[\\\"Name\\\"].lower() in wanted]; pathlib.Path('preparer_env/torch-constraints.txt').write_text('\\n'.join(rows)+'\\n')\""
      }
    },
    {
      "method": "shell.run",
      "params": {
        "venv": "preparer_env",
        "env": {
          "UV_CONSTRAINT": "preparer_env/torch-constraints.txt",
          "PIP_CONSTRAINT": "preparer_env/torch-constraints.txt"
        },
        "message": [
          "uv pip install -r requirements-preparer.txt"
        ]
      }
    },
    {
      "when": "{{platform === 'linux' && gpu === 'amd'}}",
      "method": "shell.run",
      "params": {
        "venv": "preparer_env",
        "env": {
          "UV_CONSTRAINT": "preparer_env/torch-constraints.txt",
          "PIP_CONSTRAINT": "preparer_env/torch-constraints.txt"
        },
        "message": "uv pip install -r requirements-diarization.txt"
      }
    },
    {
      "method": "script.start",
      "params": {
        "uri": "llama_cpp.js",
        "params": {
          "path": ".",
          "venv": "preparer_env",
          "constraints": "preparer_env/torch-constraints.txt"
        }
      }
    },
    {
      "when": "{{!exists('whisper.cpp')}}",
      "method": "shell.run",
      "params": {
        "message": [
          "git init whisper.cpp",
          `git -C whisper.cpp remote add origin ${whisperAssets.source_repo}`,
          `git -C whisper.cpp fetch --depth 1 origin ${whisperAssets.source_commit}`,
          "git -C whisper.cpp checkout --detach FETCH_HEAD"
        ]
      }
    },
    {
      "when": "{{!exists('models/whisper.cpp/ggml-small.en.bin')}}",
      "method": "fs.download",
      "params": {
        "url": `https://huggingface.co/${whisperAssets.model_repo}/resolve/${whisperAssets.model_revision}/${whisperAssets.model_filename}`,
        "dir": "models/whisper.cpp"
      }
    },
    {
      "method": "shell.run",
      "params": {
        "venv": "app/env",
        "message": "python tools/verify_whisper_assets.py"
      }
    },
    {
      "when": "{{platform === 'linux' && gpu === 'amd'}}",
      "method": "shell.run",
      "params": {
        "path": "whisper.cpp",
        "message": "cmake -S . -B build -DGGML_HIP=ON -DAMDGPU_TARGETS=\"$(rocminfo | awk '/Name: *gfx/{print $2; exit}')\""
      }
    },
    {
      "when": "{{gpu === 'nvidia'}}",
      "method": "shell.run",
      "params": {
        "path": "whisper.cpp",
        "message": "cmake -S . -B build -DGGML_CUDA=ON"
      }
    },
    {
      "when": "{{platform === 'darwin'}}",
      "method": "shell.run",
      "params": {
        "path": "whisper.cpp",
        "message": "cmake -S . -B build -DGGML_METAL=ON"
      }
    },
    {
      "when": "{{!(platform === 'linux' && gpu === 'amd') && gpu !== 'nvidia' && platform !== 'darwin'}}",
      "method": "shell.run",
      "params": {
        "path": "whisper.cpp",
        "message": "cmake -S . -B build"
      }
    },
    {
      "method": "shell.run",
      "params": {
        "path": "whisper.cpp",
        "message": "cmake --build build --config Release -j"
      }
    },
    {
      "method": "notify",
      "params": {
        "html": "Voice tools installed. Configure your model paths in Voice Lab / Preparer before use. Speaker diarization also requires accepting the Hugging Face model terms."
      }
    }
  ]
}
