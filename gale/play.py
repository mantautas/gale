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

from gale.engine.decode import Encoder, decode_frames, probe, write_jpeg
from gale.engine.gl import create_context
from gale.look import SLIDERS, Look
from gale.render import make_input_texture
from gale.stack import build_look

STATIC = Path(__file__).parent / "static"
OUT_DIR = Path("out")
STILLS_DIR = OUT_DIR / "stills"
ASSETS_DIR = Path("assets")
FRAME_PATH = OUT_DIR / "play_frame.jpg"
PREVIEW_PATH = OUT_DIR / "play_preview.mp4"
HOST, PORT = "127.0.0.1", 8765
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".mkv", ".avi", ".webm", ".mpg", ".mpeg"}


def _even(n: int) -> int:
    return n - (n % 2)


def list_clips() -> list[dict]:
    if not ASSETS_DIR.exists():
        return []
    clips = []
    for p in sorted(ASSETS_DIR.rglob("*")):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            rel = p.relative_to(ASSETS_DIR)
            clips.append({"name": str(rel), "path": str(p)})
    return clips


def resolve_clip(name_or_path: str) -> Path:
    """Only allow video files inside assets/."""
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
            if resolved.suffix.lower() in VIDEO_EXTS:
                return resolved
    raise ValueError(f"clip not found in assets/: {name_or_path}")


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
        path = str(resolve_clip(path))
        info = probe(path)
        width = _even(self.preview_width)
        height = _even(int(self.preview_width * info.height / info.width))
        preview_fps = min(30.0, info.fps)
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
        self.frames = frames
        self.src_fps = info.fps
        self.preview_fps = preview_fps
        self.width = width
        self.height = height
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
        print(f"cached {len(self.frames)} frames from {Path(path).name}", flush=True)

    def clip_state(self) -> dict:
        current = Path(self.input).resolve()
        clips = list_clips()
        current_path = None
        for c in clips:
            if Path(c["path"]).resolve() == current:
                current_path = c["path"]
                break
        if current_path is None and self.input:
            clips.insert(0, {"name": Path(self.input).name, "path": self.input})
            current_path = self.input
        return {
            "clips": clips,
            "source": current_path,
            "duration": self.duration,
        }

    def _apply_range(self, start_i: int, end_i: int) -> np.ndarray:
        """Run frames [start_i, end_i] inclusive through the stack; return last image."""
        self.stack.reset()
        last = None
        for i in range(start_i, end_i + 1):
            video_t = self.video_start + i / self.preview_fps
            t = self.song_offset + video_t
            frame = self.frames[i]
            self.tex.write(np.ascontiguousarray(frame[::-1]).tobytes())
            self.stack.apply(self.tex, t)
            last = self.stack.read()
        assert last is not None
        return last

    def index_at(self, t: float) -> int:
        i = int(round((t - self.video_start) * self.preview_fps))
        return max(0, min(len(self.frames) - 1, i))

    def render_frame(self, t: float) -> None:
        end = self.index_at(t)
        start = max(0, end - 24)  # warmup so trails exist
        image = self._apply_range(start, end)
        write_jpeg(str(FRAME_PATH), image)

    def export_still(self, t: float) -> Path:
        """Write a unique jpeg + look yaml into out/stills/. Frame preview is left alone."""
        end = self.index_at(t)
        start = max(0, end - 24)
        image = self._apply_range(start, end)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        ov = self.params.overlay.mode
        geo = self.params.geo.mode
        stem = f"{stamp}_t{t:.1f}_{ov}_{geo}"
        img_path = STILLS_DIR / f"{stem}.jpg"
        yaml_path = STILLS_DIR / f"{stem}.yaml"
        write_jpeg(str(img_path), image)
        write_jpeg(str(FRAME_PATH), image)
        self.params.save(yaml_path)
        return img_path

    def render_preview(self, t: float, duration: float) -> None:
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
                self.stack.apply(self.tex, self.song_offset + video_t)
                enc.write(self.stack.read())


SESSION: Session | None = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        if args and str(args[0]).startswith("POST"):
            print(fmt % args, flush=True)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
                SESSION.render_frame(float(body.get("t", 0)))
                self._send(200, FRAME_PATH.read_bytes(), "image/jpeg")
                return
            if path == "/api/export":
                path_out = SESSION.export_still(float(body.get("t", 0)))
                payload = {"ok": True, "path": str(path_out), "name": path_out.name}
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
        clips = list_clips()
        if not clips:
            raise SystemExit("no input video and nothing in assets/")
        args.input = clips[0]["path"]
    SESSION = Session(args)

    httpd = HTTPServer((HOST, args.port), Handler)
    url = f"http://{HOST}:{args.port}"
    print(f"play: {url}", flush=True)
    webbrowser.open(url)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
