import re
from pathlib import Path

EFFECTS_DIR = Path(__file__).parent
_INCLUDE = re.compile(r'^[ \t]*#include\s+"([^"]+)"', re.MULTILINE)


def load_effect(name: str) -> str:
    """Load a fragment shader, resolving `#include "file.glsl"` relative to this dir."""
    return _resolve(EFFECTS_DIR / f"{name}.glsl", set())


def _resolve(path: Path, seen: set[Path]) -> str:
    path = path.resolve()
    if path in seen:
        raise RuntimeError(f"circular include: {path.name}")
    if not path.exists():
        raise FileNotFoundError(f"no shader at {path}")
    seen.add(path)
    src = path.read_text()

    def repl(match: re.Match) -> str:
        body = _resolve(EFFECTS_DIR / match.group(1), seen)
        body = re.sub(r"^\s*#version[^\n]*\n", "", body)
        return body

    return _INCLUDE.sub(repl, src)
