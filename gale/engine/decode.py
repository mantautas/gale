"""FFmpeg pipe-based decode/encode using the imageio-ffmpeg bundled binary.

No system ffmpeg required: imageio-ffmpeg ships a static ffmpeg build
(including libx264) as a Python wheel.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass

import imageio_ffmpeg
import numpy as np

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float


def probe(path: str) -> VideoInfo:
    """Extract basic stream info by parsing `ffmpeg -i` stderr output."""
    proc = subprocess.run([FFMPEG, "-i", path], capture_output=True, text=True)
    info = proc.stderr

    size = re.search(r"(\d{2,5})x(\d{2,5})", info)
    if not size:
        raise ValueError(f"could not parse resolution from ffmpeg output for {path}")
    width, height = int(size.group(1)), int(size.group(2))

    fps_match = re.search(r"([\d.]+)\s*(?:fps|tbr)", info)
    fps = float(fps_match.group(1)) if fps_match else 30.0

    dur_match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", info)
    duration = 0.0
    if dur_match:
        h, m, s = dur_match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)

    return VideoInfo(width=width, height=height, fps=fps, duration=duration)


def decode_frame(
    path: str,
    width: int,
    height: int,
    start: float = 0.0,
) -> np.ndarray:
    """Decode a single frame at `start` seconds, scaled to width x height."""
    frames = list(
        decode_frames(path, width, height, start=start, duration=None, fps=None, max_frames=1)
    )
    if not frames:
        raise ValueError(f"could not decode a frame from {path} at t={start:.3f}")
    return frames[0]


def decode_frames(
    path: str,
    width: int,
    height: int,
    start: float = 0.0,
    duration: float | None = None,
    fps: float | None = None,
    max_frames: int | None = None,
) -> Iterator[np.ndarray]:
    """Yield frames as (H, W, 3) uint8 RGB arrays, top row first.

    `width`/`height` are the output size (ffmpeg will scale if they
    differ from the source). `fps` caps the output framerate.
    """
    cmd = [FFMPEG]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    if max_frames is not None:
        cmd += ["-frames:v", str(max_frames)]
    vf = [f"scale={width}:{height}"]
    if fps is not None:
        vf.append(f"fps={fps:.6f}")
    cmd += ["-vf", ",".join(vf), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8
    )
    assert proc.stdout is not None
    frame_size = width * height * 3
    try:
        while True:
            data = proc.stdout.read(frame_size)
            if len(data) < frame_size:
                break
            yield np.frombuffer(data, np.uint8).reshape((height, width, 3))
    finally:
        proc.stdout.close()
        proc.wait()


class Encoder:
    """Encode raw RGB frames to mp4 (libx264), optionally muxing an audio track."""

    def __init__(
        self,
        path: str,
        width: int,
        height: int,
        fps: float,
        audio: str | None = None,
        audio_offset: float = 0.0,
        crf: int = 18,
    ):
        cmd = [
            FFMPEG,
            "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", f"{fps:.6f}",
            "-i", "-",
        ]
        if audio:
            if audio_offset > 0:
                cmd += ["-ss", f"{audio_offset:.3f}"]
            cmd += [
                "-i", audio,
                "-map", "0:v", "-map", "1:a",
                "-c:a", "aac", "-shortest",
            ]
        cmd += [
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            path,
        ]
        import tempfile

        self._stderr_log = tempfile.NamedTemporaryFile(
            mode="w+b", prefix="gale-enc-", suffix=".log", delete=False
        )
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stderr=self._stderr_log
        )

    def write(self, frame: np.ndarray) -> None:
        """Write one (H, W, 3) uint8 RGB frame (top row first)."""
        assert self.proc.stdin is not None
        self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.close()
        except BrokenPipeError:
            pass
        self.proc.wait()
        self._stderr_log.flush()
        if self.proc.returncode != 0:
            self._stderr_log.seek(0)
            tail = self._stderr_log.read().decode(errors="replace")[-2000:]
            raise RuntimeError(
                f"ffmpeg encoder exited with {self.proc.returncode}:\n{tail}"
            )

    def __enter__(self) -> "Encoder":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def write_jpeg(path: str, frame: np.ndarray, quality: int = 3) -> None:
    """Encode one RGB uint8 frame to JPEG via ffmpeg. quality 2–5, lower is better."""
    h, w = frame.shape[:2]
    cmd = [
        FFMPEG, "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{w}x{h}", "-i", "-",
        "-frames:v", "1",
        "-q:v", str(quality),
        path,
    ]
    proc = subprocess.run(cmd, input=np.ascontiguousarray(frame).tobytes(), capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace")[-1000:])
