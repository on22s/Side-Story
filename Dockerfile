FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime

WORKDIR /alexandria

# Audio processing and the shared GPU safety wrappers (flock/setsid/timeout).
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libsndfile1 util-linux coreutils && \
    rm -rf /var/lib/apt/lists/*

# Preserve the image's CUDA torch stack during transitive dependency installs.
COPY app/requirements.txt /alexandria/app/requirements.txt
RUN python -c "import importlib.metadata as m, pathlib; names={'torch','torchvision','torchaudio','triton'}; pathlib.Path('/tmp/torch-constraints.txt').write_text('\n'.join(f'{d.metadata[\"Name\"]}=={d.version}' for d in m.distributions() if d.metadata['Name'].lower() in names)+'\n')" && \
    pip install --no-cache-dir -c /tmp/torch-constraints.txt -r app/requirements.txt && \
    pip install --no-cache-dir -c /tmp/torch-constraints.txt qwen-tts==0.1.1

# Runtime application code. Optional native Voice Tools are not built here.
COPY app/ /alexandria/app/
COPY default_prompts*.txt review_prompts.txt persona_prompts.txt pronunciation.json /alexandria/
COPY *.py /alexandria/
COPY gpu_job.sh gpu_pause.sh /alexandria/
COPY run_chains/lib/ /alexandria/run_chains/lib/
COPY tools/voice_lab/ /alexandria/tools/voice_lab/
COPY builtin_lora/ /alexandria/builtin_lora/
COPY LICENSE THIRD_PARTY_NOTICES.md icon.png /alexandria/

# Use one mutable data root while keeping older code/integrations and Compose
# host directories working. Never copy host runtime data into the image.
RUN mkdir -p /alexandria/runtime/uploads /alexandria/config && \
    for dir in scripts designed_voices clone_voices lora_models lora_datasets dataset_builder voicelines; do \
        mkdir -p "/alexandria/runtime/$dir" && \
        rm -rf "/alexandria/$dir" && \
        ln -s "/alexandria/runtime/$dir" "/alexandria/$dir" || exit 1; \
    done && \
    rm -rf /alexandria/app/uploads && \
    ln -s /alexandria/runtime/uploads /alexandria/app/uploads

# Docker needs a non-loopback container bind; Compose publishes only to the
# host loopback. Enable authentication before publishing to another network.
ENV ALEXANDRIA_HOST=0.0.0.0
ENV ALEXANDRIA_DATA_DIR=/alexandria/runtime
ENV ALEXANDRIA_CONFIG_PATH=/alexandria/config/config.json
EXPOSE 4200

CMD ["python", "app/app.py"]
