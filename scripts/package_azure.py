"""Package Azure runtime code/data; exclude credentials and user storage."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = ("data", "static", "scripts")
BLOCKED_PARTS = {"__pycache__", ".git", ".venv", "node_modules", ".pytest_cache", "uploads"}
BLOCKED_SUFFIXES = {".pyc", ".sqlite", ".sqlite3", ".db", ".pem", ".key", ".pfx", ".log"}


def runtime_files():
    files = set(ROOT.glob("*.py"))
    files.update(ROOT / name for name in ("requirements.txt", "gem-dashboard (1).zip"))
    for directory in RUNTIME_DIRS:
        files.update((ROOT / directory).rglob("*"))
    for path in sorted(files):
        relative = path.relative_to(ROOT)
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in BLOCKED_PARTS or part.startswith(".env") for part in relative.parts):
            continue
        if path.suffix.lower() in BLOCKED_SUFFIXES:
            continue
        yield path, relative.as_posix()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        raise SystemExit("Write deployment archives outside the repository.")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path, name in runtime_files():
            content = path.read_bytes()
            archive.writestr(name, content)
            manifest.append({"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"archive": str(output), "files": len(manifest), "bytes": output.stat().st_size,
                      "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
