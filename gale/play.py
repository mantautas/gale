"""Local look editor: sliders in the browser, live frame + short motion preview.

Runs on the main thread so the GL context stays valid. Open
http://127.0.0.1:8765 after launch.
"""

from __future__ import annotations

import argparse
import json
import webbrowser
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
FRAME_PATH = OUT_DIR / "play_frame.jpg"
PREVIEW_PATH = OUT_DIR / "play_preview.mp4"
HOST, PORT = "127.0.0.1", 8765


def _even(n: int) -> int:
    return n - (n % 2)


class Session:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.look_path = Path(args.look)
        self.params = Look.load(self.look_path) if self.look_path.exists() else Look()
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        info = probe(args.input)
        self.src_fps = info.fps
        self.preview_fps = min(30.0, info.fps)
        self.width = _even(args.width)
        self.height = _even(int(args.width * info.height / info.width))
        self.duration = args.duration or info.duration
        self.song_offset = args.song_offset
        self.audio = args.audio
        self.video_start = args.start

        print(
            f"decoding preview {self.width}x{self.height} @ {self.preview_fps:.0f} fps…",
            flush=True,
        )
        self.frames = [
            np.copy(f)
            for f in decode_frames(
                args.input,
                self.width,
                self.height,
                start=args.start,
                duration=self.duration,
                fps=self.preview_fps,
            )
        ]
        if not self.frames:
            raise SystemExit("no frames decoded for preview")
        print(f"cached {len(self.frames)} frames", flush=True)

        self.ctx = create_context()
        self.stack = build_look(
            self.ctx,
            args.analysis,
            self.width,
            self.height,
            self.preview_fps,
            self.params,
        )
        self.tex = make_input_texture(self.ctx, self.width, self.height)

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
                "duration": SESSION.duration,
            }
            self._send(200, json.dumps(payload).encode(), "application/json")
            return
        if path == "/media/preview.mp4":
            data = PREVIEW_PATH.read_bytes() if PREVIEW_PATH.exists() else b""
            self._send(200 if data else 404, data, "video/mp4")
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
            if path == "/api/preview":
                SESSION.render_preview(float(body.get("t", 0)), float(body.get("duration", 4)))
                self._send(200, b'{"ok":true}', "application/json")
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
    p.add_argument("input", help="input video file")
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
    SESSION = Session(args)

    httpd = HTTPServer((HOST, args.port), Handler)
    url = f"http://{HOST}:{args.port}"
    print(f"play: {url}", flush=True)
    webbrowser.open(url)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
