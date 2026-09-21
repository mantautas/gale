"""Local look editor: sliders in the browser, live frame + short motion preview.

Runs on the main thread so the GL context stays valid. Open
http://127.0.0.1:8765 after launch.
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from gale.engine.decode import Encoder, decode_frame, decode_frames, probe, write_jpeg
from gale.engine.gl import create_context
from gale.look import SLIDERS, Look
from gale.render import make_input_texture
from gale.stack import build_look, resolve_bindings
from gale.timeline import Timeline

STATIC = Path(__file__).parent / "static"
OUT_DIR = Path("out")
STILLS_DIR = OUT_DIR / "stills"
ASSETS_DIR = Path("assets")
FRAME_PATH = OUT_DIR / "play_frame.jpg"
PREVIEW_PATH = OUT_DIR / "play_preview.mp4"
HOST, PORT = "127.0.0.1", 8765
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".mkv", ".avi", ".webm", ".mpg", ".mpeg"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS
WARMUP_FRAMES = 12


def _even(n: int) -> int:
    return n - (n % 2)


def media_kind(path: Path | str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTS:
        return "photo"
    if suffix in VIDEO_EXTS:
        return "video"
    raise ValueError(f"unsupported media: {path}")


def list_media() -> list[dict]:
    if not ASSETS_DIR.exists():
        return []
    items = []
    for p in sorted(ASSETS_DIR.rglob("*")):
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS:
            rel = p.relative_to(ASSETS_DIR)
            items.append({"name": str(rel), "path": str(p), "kind": media_kind(p)})
    return items


def resolve_source(name_or_path: str) -> Path:
    """Only allow media files inside assets/."""
    raw = Path(name_or_path)
    candidates = [raw]
    if not raw.is_absolute():
        candidates.append(ASSETS_DIR / raw)
        candidates.append(ASSETS_DIR / raw.name)
    assets_root = ASSETS_DIR.resolve()
    for cand in candidates:
        if not cand.exists():
            continue
        resolved = cand.resolve()
        if assets_root == resolved.parent or assets_root in resolved.parents:
            if resolved.suffix.lower() in MEDIA_EXTS:
                return resolved
    raise ValueError(f"media not found in assets/: {name_or_path}")


class Session:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.look_path = Path(args.look)
        self.params = Look.load(self.look_path) if self.look_path.exists() else Look()
        self.preview_width = args.width
        self.song_offset = args.song_offset
        self.audio = args.audio
        self.analysis = args.analysis
        self.ctx = None
        self.stack = None
        self.tex = None
        self.frames: list = []
        self.input = ""
        self.width = 0
        self.height = 0
        self.preview_fps = 30.0
        self.src_fps = 30.0
        self.duration = 0.0
        self.video_start = 0.0
        self.kind = "video"
        self.src_width = 0
        self.src_height = 0
        self._native_stack = None
        self._native_tex = None
        self._native_size = None
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        STILLS_DIR.mkdir(parents=True, exist_ok=True)
        self.ctx = create_context()
        self.load_source(args.input, start=args.start, duration=args.duration)

    def load_source(
        self,
        path: str,
        start: float = 0.0,
        duration: float | None = None,
    ) -> None:
        path = str(resolve_source(path))
        kind = media_kind(path)
        info = probe(path)
        src_w = _even(max(info.width, 2))
        src_h = _even(max(info.height, 2))
        width = _even(self.preview_width)
        height = _even(int(self.preview_width * src_h / src_w))

        if kind == "photo":
            preview_fps = 30.0
            clip_duration = duration if duration is not None else (self._song_duration() or 1.0)
            print(f"loading photo {path} preview {width}x{height} (native {src_w}x{src_h})", flush=True)
            frames = [decode_frame(path, width, height, start=0.0)]
            start = 0.0
        else:
            preview_fps = min(30.0, info.fps if info.fps > 1 else 30.0)
            clip_duration = duration if duration is not None else info.duration
            print(
                f"decoding {path} {width}x{height} @ {preview_fps:.0f} fps…",
                flush=True,
            )
            frames = [
                np.copy(f)
                for f in decode_frames(
                    path, width, height, start=start, duration=clip_duration, fps=preview_fps
                )
            ]
        if not frames:
            raise ValueError(f"no frames decoded from {path}")

        rebuild = (
            self.stack is None
            or (width, height) != (self.width, self.height)
            or preview_fps != self.preview_fps
        )
        self.input = path
        self.kind = kind
        self.frames = frames
        self.src_fps = info.fps if info.fps > 1 else 30.0
        self.preview_fps = preview_fps
        self.width = width
        self.height = height
        self.src_width = src_w
        self.src_height = src_h
        self.duration = clip_duration
        self.video_start = start
        if rebuild:
            self.stack = build_look(
                self.ctx,
                self.analysis,
                self.width,
                self.height,
                self.preview_fps,
                self.params,
            )
            self.tex = make_input_texture(self.ctx, self.width, self.height)
        else:
            self.stack.reset()
        print(f"cached {len(self.frames)} frames from {Path(path).name} ({kind})", flush=True)

    def _song_duration(self) -> float | None:
        if not self.analysis:
            return None
        try:
            return float(json.loads(Path(self.analysis).read_text())["duration"])
        except (OSError, KeyError, ValueError, TypeError):
            return None

    def clip_state(self) -> dict:
        current = Path(self.input).resolve()
        clips = list_media()
        current_path = None
        for c in clips:
            if Path(c["path"]).resolve() == current:
                current_path = c["path"]
                break
        if current_path is None and self.input:
            clips.insert(
                0,
                {
                    "name": Path(self.input).name,
                    "path": self.input,
                    "kind": self.kind,
                },
            )
            current_path = self.input
        return {
            "clips": clips,
            "source": current_path,
            "kind": self.kind,
            "duration": self.duration,
            "native_width": self.src_width,
            "native_height": self.src_height,
        }

    def clip_u_at(self, t: float) -> float:
        """Clip-local 0..1 progress for automation."""
        dur = max(self.duration, 1e-6)
        if self.kind == "photo":
            return max(0.0, min(1.0, t / dur))
        return max(0.0, min(1.0, (t - self.video_start) / dur))

    def resolved_at(self, t: float) -> dict:
        """Evaluated bindable params at look time t (same clock as Frame)."""
        song_t = self.song_offset + t
        clip_u = self.clip_u_at(t)
        tl = None
        if self.analysis:
            try:
                tl = Timeline(self.analysis, self.preview_fps)
            except (OSError, KeyError, ValueError, TypeError):
                tl = None
        return resolve_bindings(self.params, tl, song_t, clip_u)

    def _apply_range(self, start_i: int, end_i: int) -> np.ndarray:
        """Run frames [start_i, end_i] inclusive through the stack; return last image."""
        self.stack.reset()
        last = None
        for i in range(start_i, end_i + 1):
            video_t = self.video_start + i / self.preview_fps
            t = self.song_offset + video_t
            frame = self.frames[i]
            self.tex.write(np.ascontiguousarray(frame[::-1]).tobytes())
            self.stack.apply(self.tex, t, self.clip_u_at(video_t))
            last = self.stack.read()
        assert last is not None
        return last

    def index_at(self, t: float) -> int:
        if self.kind == "photo":
            return 0
        i = int(round((t - self.video_start) * self.preview_fps))
        return max(0, min(len(self.frames) - 1, i))

    def render_frame(self, t: float) -> None:
        if self.kind == "photo":
            image = self._apply_photo_preview(t)
        else:
            end = self.index_at(t)
            start = max(0, end - WARMUP_FRAMES)
            image = self._apply_range(start, end)
        write_jpeg(str(FRAME_PATH), image)

    def _apply_photo_preview(self, t: float) -> np.ndarray:
        self.stack.reset()
        frame = self.frames[0]
        last = None
        uniform_t = self.song_offset + t
        clip_u = self.clip_u_at(t)
        for _ in range(WARMUP_FRAMES):
            self.tex.write(np.ascontiguousarray(frame[::-1]).tobytes())
            self.stack.apply(self.tex, uniform_t, clip_u)
            last = self.stack.read()
        assert last is not None
        return last

    def _native_pass(
        self,
        frames: list[np.ndarray],
        times: list[float],
        clip_us: list[float],
    ) -> np.ndarray:
        h, w = frames[0].shape[:2]
        w, h = _even(w), _even(h)
        if self._native_size != (w, h):
            print(f"native stack {w}x{h}", flush=True)
            self._native_stack = build_look(
                self.ctx,
                self.analysis,
                w,
                h,
                self.src_fps,
                self.params,
            )
            self._native_tex = make_input_texture(self.ctx, w, h)
            self._native_size = (w, h)
        assert self._native_stack is not None and self._native_tex is not None
        self._native_stack.reset()
        last = None
        for frame, t, clip_u in zip(frames, times, clip_us):
            self._native_tex.write(np.ascontiguousarray(frame[::-1]).tobytes())
            self._native_stack.apply(self._native_tex, t, clip_u)
            last = self._native_stack.read()
        assert last is not None
        return last

    def export_still(self, t: float) -> Path:
        """Full-resolution JPEG + look yaml into out/stills/."""
        w, h = self.src_width, self.src_height
        if self.kind == "photo":
            frame = decode_frame(self.input, w, h, start=0.0)
            frames = [frame] * WARMUP_FRAMES
            times = [self.song_offset + t] * WARMUP_FRAMES
            clip_us = [self.clip_u_at(t)] * WARMUP_FRAMES
        else:
            warmup_s = WARMUP_FRAMES / max(self.src_fps, 1.0)
            start = max(0.0, t - warmup_s)
            frames = list(
                decode_frames(
                    self.input,
                    w,
                    h,
                    start=start,
                    duration=warmup_s + (1.0 / max(self.src_fps, 1.0)),
                    fps=self.src_fps,
                )
            )
            if not frames:
                frames = [decode_frame(self.input, w, h, start=t)]
            times = [self.song_offset + start + i / max(self.src_fps, 1.0) for i in range(len(frames))]
            clip_us = [
                self.clip_u_at(start + i / max(self.src_fps, 1.0)) for i in range(len(frames))
            ]

        image = self._native_pass(frames, times, clip_us)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        ov = self.params.overlay.mode
        geo = self.params.geo.mode
        stem = f"{stamp}_t{t:.1f}_{ov}_{geo}_{w}x{h}"
        img_path = STILLS_DIR / f"{stem}.jpg"
        yaml_path = STILLS_DIR / f"{stem}.yaml"
        write_jpeg(str(img_path), image, quality=2)
        self.params.save(yaml_path)
        print(f"kept {img_path}", flush=True)
        return img_path

    def render_preview(self, t: float, duration: float) -> None:
        if self.kind == "photo":
            raise ValueError("Loop 4s is video-only")
        start = self.index_at(t)
        n = max(1, int(duration * self.preview_fps))
        end = min(len(self.frames) - 1, start + n - 1)
        self.stack.reset()
        audio_t = self.song_offset + self.video_start + start / self.preview_fps
        with Encoder(
            str(PREVIEW_PATH),
            self.width,
            self.height,
            self.preview_fps,
            audio=self.audio,
            audio_offset=audio_t,
            crf=23,
        ) as enc:
            for i in range(start, end + 1):
                video_t = self.video_start + i / self.preview_fps
                self.tex.write(np.ascontiguousarray(self.frames[i][::-1]).tobytes())
                self.stack.apply(
                    self.tex,
                    self.song_offset + video_t,
                    self.clip_u_at(video_t),
                )
                enc.write(self.stack.read())


SESSION: Session | None = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        if args and str(args[0]).startswith("POST"):
            print(fmt % args, flush=True)

    def _send(
        self,
        code: int,
        body: bytes,
        content_type: str,
        extra_headers: dict | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw or b"{}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, (STATIC / "play.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/state":
            assert SESSION is not None
            payload = {
                "look": SESSION.params.to_dict(),
                "schema": SLIDERS,
                **SESSION.clip_state(),
            }
            self._send(200, json.dumps(payload).encode(), "application/json")
            return
        if path == "/media/preview.mp4":
            data = PREVIEW_PATH.read_bytes() if PREVIEW_PATH.exists() else b""
            self._send(200 if data else 404, data, "video/mp4")
            return
        if path == "/media/frame.jpg":
            data = FRAME_PATH.read_bytes() if FRAME_PATH.exists() else b""
            self._send(200 if data else 404, data, "image/jpeg")
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        assert SESSION is not None
        path = urlparse(self.path).path
        body = self._read_json()
        if "look" in body:
            SESSION.params.replace(body["look"])
        try:
            if path == "/api/frame":
                t = float(body.get("t", 0))
                SESSION.render_frame(t)
                resolved = SESSION.resolved_at(t)
                self._send(
                    200,
                    FRAME_PATH.read_bytes(),
                    "image/jpeg",
                    extra_headers={
                        "X-Gale-Resolved": json.dumps(resolved),
                        "Access-Control-Expose-Headers": "X-Gale-Resolved",
                    },
                )
                return
            if path == "/api/resolve":
                t = float(body.get("t", 0))
                payload = {"ok": True, "resolved": SESSION.resolved_at(t)}
                self._send(200, json.dumps(payload).encode(), "application/json")
                return
            if path == "/api/export":
                path_out = SESSION.export_still(float(body.get("t", 0)))
                payload = {
                    "ok": True,
                    "path": str(path_out),
                    "name": path_out.name,
                    "width": SESSION.src_width,
                    "height": SESSION.src_height,
                }
                self._send(200, json.dumps(payload).encode(), "application/json")
                return
            if path == "/api/preview":
                SESSION.render_preview(float(body.get("t", 0)), float(body.get("duration", 4)))
                self._send(200, b'{"ok":true}', "application/json")
                return
            if path == "/api/source":
                src = body.get("path") or body.get("source")
                if not src:
                    self._send(400, b"missing path", "text/plain")
                    return
                SESSION.load_source(src)
                payload = {"ok": True, **SESSION.clip_state()}
                self._send(200, json.dumps(payload).encode(), "application/json")
                return
            if path == "/api/look":
                SESSION.params.replace(body)
                SESSION.params.save(SESSION.look_path)
                self._send(200, b'{"ok":true}', "application/json")
                return
        except Exception as exc:
            self._send(500, str(exc).encode(), "text/plain")
            return
        self._send(404, b"not found", "text/plain")


def main() -> None:
    global SESSION
    p = argparse.ArgumentParser(description="gale look editor")
    p.add_argument("input", nargs="?", default=None, help="input video (default: first clip in assets/)")
    p.add_argument("--analysis", default="out/analysis.json")
    p.add_argument("--look", default="configs/look.yaml")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--duration", type=float, default=None)
    p.add_argument("--song-offset", type=float, default=0.0)
    p.add_argument("--audio", default=None)
    p.add_argument("--width", type=int, default=540, help="preview width")
    p.add_argument("--port", type=int, default=PORT)
    args = p.parse_args()

    analysis = args.analysis if Path(args.analysis).exists() else None
    args.analysis = analysis
    if not args.input:
        clips = list_media()
        if not clips:
            raise SystemExit("no input and nothing in assets/")
        videos = [c for c in clips if c["kind"] == "video"]
        args.input = (videos or clips)[0]["path"]
    SESSION = Session(args)

    httpd = HTTPServer((HOST, args.port), Handler)
    url = f"http://{HOST}:{args.port}"
    print(f"play: {url}", flush=True)
    webbrowser.open(url)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
