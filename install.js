// Lean runtime install. Native Voice Lab / Preparer builds are opt-in.
module.exports = {
  "requires": {
    "bundle": "ai"
  },
  "run": [
    {
      "when": "{{!exists('app/env')}}",
      "method": "shell.run",
      "params": {
        "path": "app",
        "message": "uv venv --python 3.10 env"
      }
    },
    {
      "method": "script.start",
      "params": {
        "uri": "torch.js",
        "params": {
          "path": "app",
          "venv": "env",
          "flashattention": true
        }
      }
    },
    {
      "method": "shell.run",
      "params": {
        "venv": "env",
        "path": "app",
        "message": "python -c \"import importlib.metadata as m, pathlib; wanted={'torch','torchvision','torchaudio','pytorch-triton','pytorch-triton-rocm','triton-rocm'}; rows=[f'{d.metadata[\\\"Name\\\"]}=={d.version}' for d in m.distributions() if d.metadata[\\\"Name\\\"].lower() in wanted]; pathlib.Path('torch-constraints.txt').write_text('\\n'.join(rows)+'\\n')\""
      }
    },
    {
      "method": "shell.run",
      "params": {
        "venv": "env",
        "path": "app",
        "env": {
          "UV_CONSTRAINT": "torch-constraints.txt",
          "PIP_CONSTRAINT": "torch-constraints.txt"
        },
        "message": [
          "uv pip uninstall google-genai",
          "uv pip install -r requirements.txt",
          "uv pip install qwen-tts==0.1.1"
        ]
      }
    },
    {
      "when": "{{platform === 'darwin' && arch === 'arm64' && exists('mlx_env') && !exists('mlx_env/bin/python3.11')}}",
      "method": "fs.rm",
      "params": {
        "path": "mlx_env"
      }
    },
    {
      "when": "{{platform === 'darwin' && arch === 'arm64'}}",
      "method": "shell.run",
      "params": {
        "venv": "mlx_env",
        "venv_python": "3.11",
        "message": [
          "uv pip install -r requirements-mlx.txt",
          "python -c \"from huggingface_hub import snapshot_download as s; [s('Qwen/Qwen3-TTS-12Hz-1.7B-' + f) for f in ('CustomVoice', 'Base', 'VoiceDesign')]\""
        ]
      }
    },
    {
      "method": "notify",
      "params": {
        "html": "Installation Complete! Click 'Start' to launch. Optional Voice Lab / Preparer dependencies are available separately under 'Install Voice Tools'."
      }
    }
  ]
}
