"""Audio analysis: music file -> analysis.json + verification plot.

Runs once per track. Everything the renderer needs is precomputed here so
the render loop never touches audio and stays frame-deterministic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import librosa
import numpy as np

# Curve sample rate for continuous features (RMS, bands, centroid).
# ~86 Hz at sr=22050 / hop=256; renderer interpolates to frame times.
HOP_LENGTH = 256

# Frequency band edges (Hz) for band-limited onset/energy features.
BANDS = {
    "low": (20, 150),      # kick, bass
    "mid": (150, 2000),    # snare body, vocals, melody
    "high": (2000, 10000), # hats, air, sibilance
}


def _curve(times: np.ndarray, values: np.ndarray) -> dict:
    return {
        "times": np.round(times, 5).tolist(),
        "values": np.round(values, 5).tolist(),
    }


def _normalize(x: np.ndarray) -> np.ndarray:
    peak = np.max(np.abs(x))
    return x / peak if peak > 0 else x


def analyze(audio_path: str) -> dict:
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))

    # --- beats & tempo ---
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=HOP_LENGTH)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=HOP_LENGTH)

    # --- continuous curves ---
    rms = librosa.feature.rms(y=y, hop_length=HOP_LENGTH)[0]
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=HOP_LENGTH)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=HOP_LENGTH)

    curves = {
        "rms": _curve(times, _normalize(rms)),
        "centroid": _curve(times, _normalize(centroid)),
    }

    # --- per-band energy curves + band-tagged onsets ---
    stft = np.abs(librosa.stft(y, hop_length=HOP_LENGTH))
    freqs = librosa.fft_frequencies(sr=sr)
    onsets: list[dict] = []

    for band, (lo, hi) in BANDS.items():
        mask = (freqs >= lo) & (freqs < hi)
        band_energy = stft[mask].sum(axis=0)
        curves[band] = _curve(times, _normalize(band_energy))

        # onset envelope restricted to this band
        y_band = librosa.istft(
            librosa.stft(y, hop_length=HOP_LENGTH) * mask[:, None],
            hop_length=HOP_LENGTH,
        )
        env = librosa.onset.onset_strength(y=y_band, sr=sr, hop_length=HOP_LENGTH)
        env = _normalize(env)
        frames = librosa.onset.onset_detect(
            onset_envelope=env, sr=sr, hop_length=HOP_LENGTH, backtrack=True
        )
        for f in frames:
            onsets.append(
                {
                    "t": round(float(librosa.frames_to_time(f, sr=sr, hop_length=HOP_LENGTH)), 4),
                    "strength": round(float(env[f]), 4),
                    "band": band,
                }
            )

    onsets.sort(key=lambda o: o["t"])

    return {
        "source": str(audio_path),
        "duration": round(duration, 4),
        "bpm": round(float(np.atleast_1d(tempo)[0]), 2),
        "beats": np.round(beat_times, 4).tolist(),
        "onsets": onsets,
        "curves": curves,
        # section detection lands in M5
        "sections": [{"label": "all", "start": 0.0, "end": round(duration, 4)}],
    }


def plot_verification(analysis: dict, audio_path: str, out_path: str) -> None:
    """Waveform + beats/onsets overlay so sync can be eyeballed before rendering."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    fig, ax = plt.subplots(figsize=(20, 5))
    librosa.display.waveshow(y, sr=sr, ax=ax, alpha=0.6)

    for t in analysis["beats"]:
        ax.axvline(t, color="lime", alpha=0.35, lw=0.8)

    band_colors = {"low": "red", "mid": "orange", "high": "cyan"}
    for o in analysis["onsets"]:
        ax.axvline(
            o["t"],
            color=band_colors.get(o["band"], "white"),
            alpha=0.2 + 0.5 * o["strength"],
            lw=0.8,
        )

    rms = analysis["curves"]["rms"]
    ax.plot(rms["times"], np.array(rms["values"]) * 0.9, color="magenta", lw=1)

    ax.set_title(
        f"{Path(audio_path).name} — {analysis['bpm']} bpm, "
        f"{len(analysis['beats'])} beats, {len(analysis['onsets'])} onsets"
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    print(f"verification plot -> {out_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="gale audio analyzer")
    p.add_argument("audio", help="music track (wav/mp3/flac)")
    p.add_argument("--out", default="analysis.json", help="output JSON path")
    p.add_argument("--plot", default="analysis.png", help="verification plot path")
    args = p.parse_args()

    result = analyze(args.audio)
    Path(args.out).write_text(json.dumps(result))
    print(
        f"analyzed {result['duration']:.1f}s: {result['bpm']} bpm, "
        f"{len(result['beats'])} beats, {len(result['onsets'])} onsets -> {args.out}"
    )
    plot_verification(result, args.audio, args.plot)


if __name__ == "__main__":
    main()
