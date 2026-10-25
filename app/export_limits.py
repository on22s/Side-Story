"""Finite export limits shared by request validation and silent-PCM assembly.

Pydub's AudioSegment.silent() produces 11,025 Hz mono 16-bit PCM, so the
760,000 ms export pause limit corresponds to 16,758,000 bytes (about 16 MiB).
"""

SILENCE_FRAME_RATE = 11025
SILENCE_SAMPLE_WIDTH = 2
MAX_PAUSE_MS = 760_000
# The compatibility path assembles the whole book/chapter in memory. Keep a
# finite ceiling for that legacy route; ordinary PCM uses the streaming paths.
MAX_LEGACY_EXPORT_PCM_BYTES = 1024 ** 3


def get_pause_pcm_bytes(duration_ms):
    """Return the PCM bytes AudioSegment.silent() allocates for this pause."""
    frames = int(SILENCE_FRAME_RATE * (duration_ms / 1000.0))
    return max(0, frames) * SILENCE_SAMPLE_WIDTH


def get_legacy_pcm_bytes(plan):
    """Return the PCM bytes this assembled-source plan would allocate."""
    if not isinstance(plan, dict):
        raise ValueError('Legacy export plan is unavailable.')
    frames = plan.get('frames')
    channels = plan.get('channels')
    sample_width = plan.get('sample_width')
    if (type(frames) is not int or frames < 0
            or type(channels) is not int or channels <= 0
            or type(sample_width) is not int or sample_width <= 0):
        raise ValueError('Legacy export plan has an invalid PCM shape.')
    return frames * channels * sample_width


def ensure_legacy_pcm_allowed(plan):
    """Refuse a legacy whole-buffer assembly above its finite ceiling."""
    size = get_legacy_pcm_bytes(plan)
    if size > MAX_LEGACY_EXPORT_PCM_BYTES:
        raise ValueError(
            f"The compatibility export would assemble {size} bytes of PCM; "
            f"the whole-buffer fallback is limited to {MAX_LEGACY_EXPORT_PCM_BYTES} bytes. "
            "Convert the custom/unsupported chunks to ordinary PCM or split the export.")


def ensure_pause_allowed(duration_ms):
    """Reject a pause whose whole-buffer silence exceeds the export limit."""
    if duration_ms > MAX_PAUSE_MS:
        raise ValueError(
            f"An audio pause of {duration_ms} ms needs "
            f"{get_pause_pcm_bytes(duration_ms)} bytes of silence; exports allow at most "
            f"{MAX_PAUSE_MS} ms ({get_pause_pcm_bytes(MAX_PAUSE_MS)} bytes). "
            "Shorten the pause before exporting.")
