"""Render CLI: video in -> look stack -> mp4 out."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterable
from pathlib import Path

import moderngl
import numpy as np

from gale.engine.decode import Encoder, decode_frames, probe
from gale.engine.gl import create_context
from gale.look import Look
from gale.stack import Stack, build_look


def render_frames(
    frames: Iterable[np.ndarray],
    look: Stack,
    tex: moderngl.Texture,
    encoder: Encoder,
    *,
    fps: float,
    song_offset: float,
    start: float,
    duration: float,
) -> int:
    n = 0
    t0 = time.time()
    dur = max(duration, 1e-6)
    for frame in frames:
        video_t = start + n / fps
        t = song_offset + video_t
        clip_u = max(0.0, min(1.0, (video_t - start) / dur))
        tex.write(np.ascontiguousarray(frame[::-1]).tobytes())
        look.apply(tex, t, clip_u)
        encoder.write(look.read())
        n += 1
        if n % 100 == 0:
            print(f"  {n} frames ({n / (time.time() - t0):.0f} fps)", flush=True)
    return n


def make_input_texture(ctx: moderngl.Context, width: int, height: int) -> moderngl.Texture:
    tex = ctx.texture((width, height), 3)
    tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
    tex.repeat_x = False
    tex.repeat_y = False
    return tex


def main() -> None:
    p = argparse.ArgumentParser(description="gale renderer")
    p.add_argument("input", help="input video file")
    p.add_argument("output", help="output mp4 path")
    p.add_argument("--analysis", default=None, help="analysis.json from gale-analyze")
    p.add_argument("--look", default="configs/look.yaml", help="look YAML (from gale-play)")
    p.add_argument("--start", type=float, default=0.0, help="start time in video (s)")
    p.add_argument("--duration", type=float, default=None, help="duration (s)")
    p.add_argument(
        "--song-offset",
        type=float,
        default=0.0,
        help="where in the song timeline this clip sits (s)",
    )
    p.add_argument("--audio", default=None, help="audio file to mux into output")
    p.add_argument("--crf", type=int, default=18, help="x264 quality (lower=better)")
    args = p.parse_args()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    params = Look.load(args.look) if Path(args.look).exists() else Look()

    info = probe(args.input)
    print(
        f"input: {info.width}x{info.height} @ {info.fps:.3f} fps, "
        f"{info.duration:.1f}s  look={args.look}",
        flush=True,
    )

    ctx = create_context()
    stack = build_look(ctx, args.analysis, info.width, info.height, info.fps, params)
    tex = make_input_texture(ctx, info.width, info.height)

    clip_duration = args.duration if args.duration is not None else max(info.duration - args.start, 0.0)
    t0 = time.time()
    with Encoder(
        args.output,
        info.width,
        info.height,
        info.fps,
        audio=args.audio,
        audio_offset=args.song_offset,
        crf=args.crf,
    ) as enc:
        n = render_frames(
            decode_frames(
                args.input, info.width, info.height, args.start, args.duration
            ),
            stack,
            tex,
            enc,
            fps=info.fps,
            song_offset=args.song_offset,
            start=args.start,
            duration=clip_duration,
        )

    dt = time.time() - t0
    print(f"done: {n} frames in {dt:.1f}s ({n / max(dt, 1e-6):.0f} fps) -> {args.output}")
    if n == 0:
        sys.exit("error: no frames decoded")


if __name__ == "__main__":
    main()
