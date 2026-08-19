#!/usr/bin/env python3
"""Generate Alexandria's dependency-free cultivation-novel SFX starter pack."""

from __future__ import annotations

import argparse
import math
import random
import struct
import wave
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "assets" / "sfx"
SAMPLE_RATE = 24000


def _count(duration: float) -> int:
    return max(1, int(round(duration * SAMPLE_RATE)))


def _normalize(samples: Sequence[float], peak: float = 0.82) -> List[float]:
    maximum = max((abs(value) for value in samples), default=1.0)
    scale = peak / maximum if maximum > peak else 1.0
    return [max(-1.0, min(1.0, value * scale)) for value in samples]


def _write(relative: str, samples: Sequence[float], force: bool) -> bool:
    path = OUTPUT_DIR / relative
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = bytearray()
    for value in _normalize(samples):
        pcm.extend(struct.pack("<h", int(value * 32767)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(pcm))
    return True


def _noise(duration: float, seed: int, smoothing: float = 0.0) -> List[float]:
    rng = random.Random(seed)
    value = 0.0
    result = []
    for _ in range(_count(duration)):
        raw = rng.uniform(-1.0, 1.0)
        value = value * smoothing + raw * (1.0 - smoothing)
        result.append(value)
    return result


def _tone(duration: float, frequency: float, decay: float = 0.0, phase: float = 0.0) -> List[float]:
    result = []
    for index in range(_count(duration)):
        time_value = index / SAMPLE_RATE
        envelope = math.exp(-decay * time_value) if decay else 1.0
        result.append(math.sin(2.0 * math.pi * frequency * time_value + phase) * envelope)
    return result


def _chirp(duration: float, start_hz: float, end_hz: float) -> List[float]:
    result = []
    slope = (end_hz - start_hz) / max(duration, 0.001)
    for index in range(_count(duration)):
        time_value = index / SAMPLE_RATE
        phase = 2.0 * math.pi * (start_hz * time_value + 0.5 * slope * time_value * time_value)
        result.append(math.sin(phase))
    return result


def _window(samples: Sequence[float], attack: float = 0.02, release: float = 0.12) -> List[float]:
    total = len(samples)
    attack_frames = max(1, int(attack * SAMPLE_RATE))
    release_frames = max(1, int(release * SAMPLE_RATE))
    result = []
    for index, value in enumerate(samples):
        gain = min(1.0, index / attack_frames, (total - index - 1) / release_frames)
        result.append(value * max(0.0, gain))
    return result


def _mix(duration: float, tracks: Iterable[Tuple[Sequence[float], float, float]]) -> List[float]:
    result = [0.0] * _count(duration)
    for samples, gain, offset in tracks:
        start = max(0, int(offset * SAMPLE_RATE))
        for index, value in enumerate(samples):
            target = start + index
            if target >= len(result):
                break
            result[target] += value * gain
    return result


def sword_whoosh(duration: float = 0.9, seed: int = 11) -> List[float]:
    noise = _noise(duration, seed, 0.62)
    tone = _chirp(duration, 180.0, 1100.0)
    shaped = []
    for index, value in enumerate(noise):
        position = index / max(1, len(noise) - 1)
        envelope = math.sin(math.pi * position) ** 2.7
        shaped.append((value * 0.9 + tone[index] * 0.16) * envelope)
    return shaped


def sword_clash() -> List[float]:
    duration = 1.7
    tracks = [
        (_tone(duration, 870, 3.4), 0.55, 0),
        (_tone(duration, 1370, 4.1), 0.40, 0),
        (_tone(duration, 2260, 5.2), 0.25, 0),
        (_window(_noise(0.10, 21, 0.15), 0.001, 0.08), 0.65, 0),
    ]
    return _mix(duration, tracks)


def heavy_impact(duration: float = 1.3, seed: int = 31) -> List[float]:
    rumble = _tone(duration, 72, 4.0)
    body = _noise(duration, seed, 0.92)
    return [
        (rumble[index] * 0.72 + body[index] * 0.55) * math.exp(-3.2 * index / SAMPLE_RATE)
        for index in range(len(rumble))
    ]


def qi_blast() -> List[float]:
    duration = 1.6
    chirp = _chirp(duration, 120, 1450)
    air = sword_whoosh(duration, 42)
    impact = heavy_impact(1.0, 43)
    return _mix(duration, [(chirp, 0.32, 0), (air, 0.72, 0), (impact, 0.52, 0.48)])


def explosion() -> List[float]:
    duration = 2.8
    noise = _noise(duration, 51, 0.88)
    rumble = _tone(duration, 48, 1.35)
    return [
        (noise[index] * 0.92 + rumble[index] * 0.58) * math.exp(-1.25 * index / SAMPLE_RATE)
        for index in range(len(noise))
    ]


def thunder() -> List[float]:
    duration = 4.8
    base = _noise(duration, 61, 0.965)
    rumble = _tone(duration, 38, 0.42)
    crack = _window(_noise(0.18, 62, 0.18), 0.001, 0.15)
    result = _mix(duration, [(base, 0.88, 0), (rumble, 0.42, 0), (crack, 0.95, 0.04)])
    return [value * math.exp(-0.42 * index / SAMPLE_RATE) for index, value in enumerate(result)]


def spell_charge() -> List[float]:
    duration = 2.7
    chirp = _chirp(duration, 90, 760)
    shimmer = _tone(duration, 1230, 0.15)
    result = []
    for index in range(len(chirp)):
        position = index / max(1, len(chirp) - 1)
        tremolo = 0.72 + 0.28 * math.sin(2 * math.pi * 7 * index / SAMPLE_RATE)
        result.append((chirp[index] * 0.58 + shimmer[index] * 0.18) * position * tremolo)
    return _window(result, 0.08, 0.08)


def spell_release() -> List[float]:
    duration = 1.5
    return _mix(duration, [
        (_window(_chirp(0.85, 1800, 120), 0.01, 0.22), 0.55, 0),
        (heavy_impact(1.1, 72), 0.62, 0.28),
    ])


def teleport() -> List[float]:
    duration = 1.9
    up = _window(_chirp(0.9, 180, 2100), 0.04, 0.10)
    down = _window(_chirp(1.0, 2200, 120), 0.03, 0.28)
    return _mix(duration, [(up, 0.48, 0), (down, 0.58, 0.72), (sword_whoosh(1.2, 81), 0.34, 0.42)])


def barrier_hum() -> List[float]:
    duration = 4.0
    result = []
    for index in range(_count(duration)):
        time_value = index / SAMPLE_RATE
        pulse = 0.78 + 0.22 * math.sin(2 * math.pi * 0.5 * time_value)
        value = (
            math.sin(2 * math.pi * 80 * time_value) * 0.42
            + math.sin(2 * math.pi * 160 * time_value) * 0.22
            + math.sin(2 * math.pi * 480 * time_value) * 0.08
        )
        result.append(value * pulse)
    return result


def flying_whoosh() -> List[float]:
    return _mix(2.4, [(sword_whoosh(2.0, 91), 0.82, 0), (sword_whoosh(1.4, 92), 0.45, 0.7)])


def footsteps_stone() -> List[float]:
    step = heavy_impact(0.32, 101)
    return _mix(2.2, [(step, 0.58, 0.12), (step, 0.52, 0.78), (step, 0.60, 1.48)])


def door_wood() -> List[float]:
    duration = 1.9
    creak = []
    for index in range(_count(1.35)):
        time_value = index / SAMPLE_RATE
        frequency = 135 + 75 * math.sin(2 * math.pi * 1.7 * time_value)
        creak.append(math.sin(2 * math.pi * frequency * time_value) * math.sin(math.pi * time_value / 1.35))
    return _mix(duration, [(creak, 0.38, 0), (heavy_impact(0.48, 111), 0.48, 1.18)])


def sect_bell() -> List[float]:
    duration = 5.5
    return _mix(duration, [
        (_tone(duration, 196, 0.52), 0.55, 0),
        (_tone(duration, 392, 0.70), 0.35, 0),
        (_tone(duration, 590, 0.86), 0.18, 0),
        (_window(_noise(0.08, 121, 0.25), 0.001, 0.06), 0.24, 0),
    ])


def beast_roar() -> List[float]:
    duration = 2.5
    noise = _noise(duration, 131, 0.90)
    result = []
    for index, breath in enumerate(noise):
        time_value = index / SAMPLE_RATE
        frequency = 62 + 24 * math.sin(2 * math.pi * 2.1 * time_value)
        growl = math.sin(2 * math.pi * frequency * time_value)
        envelope = math.sin(math.pi * min(1.0, time_value / duration)) ** 0.7
        result.append((growl * 0.68 + breath * 0.46) * envelope)
    return _window(result, 0.10, 0.32)


def mountain_wind() -> List[float]:
    duration = 10.0
    noise = _noise(duration, 201, 0.965)
    return [
        value * (0.62 + 0.28 * math.sin(2 * math.pi * 0.11 * index / SAMPLE_RATE))
        for index, value in enumerate(noise)
    ]


def forest_night() -> List[float]:
    duration = 10.0
    bed = _noise(duration, 211, 0.985)
    tracks: List[Tuple[Sequence[float], float, float]] = [(bed, 0.32, 0)]
    for offset, frequency in [(0.7, 3100), (2.3, 2700), (4.9, 3400), (7.2, 2950), (8.6, 3250)]:
        chirp = _window(_tone(0.28, frequency), 0.02, 0.08)
        tracks.append((chirp, 0.13, offset))
    return _mix(duration, tracks)


def cave_drip() -> List[float]:
    duration = 10.0
    bed = _noise(duration, 221, 0.992)
    tracks: List[Tuple[Sequence[float], float, float]] = [(bed, 0.20, 0)]
    for offset, frequency in [(1.1, 820), (3.8, 690), (6.2, 930), (8.7, 760)]:
        drop = _window(_tone(0.62, frequency, 5.8), 0.001, 0.42)
        tracks.append((drop, 0.30, offset))
    return _mix(duration, tracks)


def rain() -> List[float]:
    duration = 10.0
    hiss = _noise(duration, 231, 0.18)
    wash = _noise(duration, 232, 0.94)
    return [(hiss[index] * 0.22 + wash[index] * 0.48) for index in range(len(hiss))]


def fire() -> List[float]:
    duration = 10.0
    bed = _noise(duration, 241, 0.93)
    result = [value * 0.38 for value in bed]
    rng = random.Random(242)
    for _ in range(34):
        start = rng.randrange(0, len(result) - 120)
        length = rng.randrange(25, 110)
        strength = rng.uniform(0.18, 0.55)
        for index in range(length):
            result[start + index] += rng.uniform(-1, 1) * strength * (1 - index / length)
    return result


def stream() -> List[float]:
    duration = 10.0
    water = _noise(duration, 251, 0.72)
    deep = _noise(duration, 252, 0.95)
    return [water[index] * 0.34 + deep[index] * 0.42 for index in range(len(water))]


GENERATORS: Dict[str, Callable[[], List[float]]] = {
    "combat/sword_whoosh.wav": sword_whoosh,
    "combat/sword_clash.wav": sword_clash,
    "combat/heavy_impact.wav": heavy_impact,
    "combat/qi_blast.wav": qi_blast,
    "combat/explosion.wav": explosion,
    "combat/thunder_strike.wav": thunder,
    "magic/spell_charge.wav": spell_charge,
    "magic/spell_release.wav": spell_release,
    "magic/teleport.wav": teleport,
    "magic/barrier_hum.wav": barrier_hum,
    "movement/flying_whoosh.wav": flying_whoosh,
    "movement/footsteps_stone.wav": footsteps_stone,
    "movement/door_wood.wav": door_wood,
    "world/sect_bell.wav": sect_bell,
    "creatures/beast_roar.wav": beast_roar,
    "ambience/mountain_wind.wav": mountain_wind,
    "ambience/forest_night.wav": forest_night,
    "ambience/cave_drip.wav": cave_drip,
    "ambience/rain.wav": rain,
    "ambience/fire.wav": fire,
    "ambience/stream.wav": stream,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite existing generated WAV files")
    args = parser.parse_args()
    written = 0
    for relative, generator in GENERATORS.items():
        if _write(relative, generator(), args.force):
            written += 1
    print(f"built-in SFX ready: {len(GENERATORS)} files ({written} written) under {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
