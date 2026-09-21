"""Mapping layer: analysis.json -> per-frame effect parameters.

All musical timing lookups live here. Effects receive plain floats,
so shaders stay dumb and the "musical feel" (envelopes, quantization)
is tuned in one place.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np


class Timeline:
    def __init__(self, analysis_path: str | Path, fps: float):
        a = json.loads(Path(analysis_path).read_text())
        self.fps = fps
        self.duration: float = a["duration"]
        self.bpm: float = a["bpm"]
        self.beat_interval = 60.0 / self.bpm
        self.beats = np.array(a["beats"])
        self.onsets = a["onsets"]
        self.sections = a.get("sections", [])

        self._curves = {
            name: (np.array(c["times"]), np.array(c["values"]))
            for name, c in a["curves"].items()
        }
        self._onsets_by_band: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for band in {o["band"] for o in self.onsets}:
            sel = [o for o in self.onsets if o["band"] == band]
            self._onsets_by_band[band] = (
                np.array([o["t"] for o in sel]),
                np.array([o["strength"] for o in sel]),
            )

    # --- continuous curves -------------------------------------------------

    def value(self, curve: str, t: float) -> float:
        """Linearly-interpolated curve value at time t (0..1 normalized)."""
        ts, vs = self._curves[curve]
        return float(np.interp(t, ts, vs))

    # --- event envelopes ---------------------------------------------------

    @staticmethod
    def _decay_after(times: np.ndarray, strengths: np.ndarray, t: float, tau: float) -> float:
        """Strength of the most recent event before t, exponentially decayed."""
        idx = int(np.searchsorted(times, t, side="right")) - 1
        if idx < 0:
            return 0.0
        dt = t - float(times[idx])
        if dt > 6 * tau:
            return 0.0
        return float(strengths[idx]) * math.exp(-dt / tau)

    def beat_pulse(self, t: float, tau: float | None = None) -> float:
        """1.0 exactly on each beat, exponential decay after.

        Default tau is half a beat — pulse dies right before the next hit.
        """
        tau = tau if tau is not None else self.beat_interval * 0.5
        return self._decay_after(self.beats, np.ones(len(self.beats)), t, tau)

    def onset_pulse(self, t: float, band: str | None = None, tau: float = 0.08) -> float:
        """Decaying envelope of the most recent onset (optionally per band)."""
        if band is None:
            return max(
                (self.onset_pulse(t, b, tau) for b in self._onsets_by_band),
                default=0.0,
            )
        if band not in self._onsets_by_band:
            return 0.0
        times, strengths = self._onsets_by_band[band]
        return self._decay_after(times, strengths, t, tau)

    def audio(self, source: str, t: float) -> float:
        """0..1 driver for modulation. Unknown / none → 0."""
        if source in (None, "", "none"):
            return 0.0
        if source == "energy":
            return 0.6 * self.value("low", t) + 0.4 * self.value("mid", t)
        if source == "beat":
            return self.beat_pulse(t)
        if source == "onset":
            return self.onset_pulse(t)
        if source == "kick":
            return self.onset_pulse(t, "low", tau=0.40)
        if source in self._curves:
            return self.value(source, t)
        return 0.0
