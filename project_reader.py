"""Prepare a bounded, read-only snapshot of project text for review."""

import argparse
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


EXCLUDED_FOLDERS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", "dist", "build", "vendor", ".next", ".cache",
    "coverage", "test-data", "uploads", ".vscode", ".idea",
}
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml",
    ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".sql",
    ".ini", ".cfg", ".sh", ".ps1", ".go", ".rs", ".java",
    ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".rst",
}
TEXT_NAMES = {"dockerfile", "makefile", "license", "readme", "pipfile", ".gitignore"}
MANIFEST_NAMES = {
    "pyproject.toml", "requirements.txt", "package.json", "cargo.toml",
    "go.mod", "dockerfile", "makefile", "pipfile", "setup.py", "setup.cfg",
    "render.yaml", "docker-compose.yml", "compose.yaml",
}
CODE_SUFFIXES = TEXT_SUFFIXES - {".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".rst"}
SENSITIVE_NAMES = {
    "credentials.json", "service-account.json", "service_account.json",
    "application_default_credentials.json", "id_rsa", "id_ed25519",
    ".npmrc", ".pypirc", ".netrc",
}
TOKEN_PATTERN = re.compile(
    r"AIza[\w-]{20,}|\bsk-[\w-]{16,}|\bgh[pousr]_[\w]{16,}|"
    r"\bAKIA[A-Z0-9]{16}\b|ya29\.[\w.~-]+"
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)[\w-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|secret[_-]?key|private[_-]?key)"
    r"[\w-]*[\"']?\s*[:=]\s*[\"'][^\"'\n]+[\"']"
)


@dataclass(frozen=True)
class SourceFile:
    path: str
    text: str
    redacted_lines: tuple[int, ...] = ()

    @property
    def line_count(self):
        return len(self.text.splitlines())

    def numbered_text(self):
        return "\n".join(f"{i}: {line}" for i, line in enumerate(self.text.splitlines(), 1))


@dataclass
class ProjectSnapshot:
    files: list[SourceFile]
    skipped: list[dict]

    def manifest(self):
        return {
            "file_count": len(self.files),
            "text_bytes": sum(len(f.text.encode("utf-8")) for f in self.files),
            "files": [{"path": f.path, "lines": f.line_count,
                       "redacted_lines": list(f.redacted_lines)} for f in self.files],
            "skipped": self.skipped,
        }


def allowed_path(value):
    """Return a normalized relative path and an exclusion reason, if any."""
    value = value.replace("\\", "/")
    parts = value.split("/")
    if (not value or len(value) > 500 or any(p in {"", ".", ".."} for p in parts)
            or any(":" in p or "\x00" in p for p in parts)):
        return value, "invalid relative path"
    path = PurePosixPath(value)
    lower = [p.lower() for p in parts]
    name = lower[-1]
    if any(p in EXCLUDED_FOLDERS or p.startswith(".") for p in lower[:-1]):
        return value, "excluded folder"
    if (name.startswith(".env") or name in SENSITIVE_NAMES
            or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}):
        return value, "credential file"
    if name.startswith(".") and name not in TEXT_NAMES:
        return value, "hidden file"
    if path.suffix.lower() not in TEXT_SUFFIXES and name not in TEXT_NAMES | MANIFEST_NAMES:
        return value, "unsupported file type"
    if name.endswith(("-lock.json", ".lock")):
        return value, "generated dependency lockfile"
    return value, None


def source_priority(name):
    path = PurePosixPath(name.replace("\\", "/"))
    if path.name.lower().startswith("readme") and len(path.parts) == 1:
        rank = 0
    elif path.name.lower() in MANIFEST_NAMES:
        rank = 1
    elif path.suffix.lower() in CODE_SUFFIXES:
        rank = 2
    else:
        rank = 3
    return rank, len(path.parts), str(path)


def collect_files(candidates, *, max_files=40, max_file_bytes=65536, max_total_bytes=160000):
    """Accept (relative_path, bytes) pairs, including future browser uploads."""
    files, skipped, seen = [], [], set()
    total = 0
    for index, (name, data) in enumerate(candidates):
        if index >= 1000:
            skipped.append({"path": "(remaining files)", "reason": "scan limit reached"})
            break
        name, reason = allowed_path(name)
        if not reason and name in seen:
            reason = "duplicate path"
        seen.add(name)
        if not reason and len(files) >= max_files:
            reason = "file count limit"
        if not reason and len(data) > max_file_bytes:
            reason = "file size limit"
        text = ""
        if not reason:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                reason = "not UTF-8 text"
        if not reason and "\x00" in text:
            reason = "binary content"
        if not reason and not text.strip():
            reason = "empty file"
        redacted = []
        if not reason:
            lines = text.splitlines()
            for number, line in enumerate(lines, 1):
                if TOKEN_PATTERN.search(line) or SECRET_ASSIGNMENT.search(line):
                    lines[number - 1] = "[credential-like value omitted]"
                    redacted.append(number)
            text = "\n".join(lines)
            size = len(text.encode("utf-8"))
            if total + size > max_total_bytes:
                reason = "total text limit"
        if reason:
            skipped.append({"path": name, "reason": reason})
        else:
            files.append(SourceFile(name, text, tuple(redacted)))
            total += size
    return ProjectSnapshot(files, skipped)


def is_link(path):
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def scan_project(folder):
    """Read ordinary files without following symbolic links or junctions."""
    root = Path(folder).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Choose a project folder.")
    candidates, skipped = [], []
    for directory, folders, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        retained = []
        for name in sorted(folders):
            path = base / name
            if name.lower() in EXCLUDED_FOLDERS or name.startswith("."):
                skipped.append({"path": path.relative_to(root).as_posix() + "/", "reason": "excluded folder"})
            elif is_link(path):
                skipped.append({"path": path.relative_to(root).as_posix() + "/", "reason": "linked folder"})
            elif len(path.relative_to(root).parts) <= 12:
                retained.append(name)
            else:
                skipped.append({"path": path.relative_to(root).as_posix() + "/", "reason": "folder depth limit"})
        folders[:] = retained
        for name in sorted(filenames):
            path = base / name
            relative = path.relative_to(root).as_posix()
            _, reason = allowed_path(relative)
            if reason:
                skipped.append({"path": relative, "reason": reason})
            elif is_link(path):
                skipped.append({"path": relative, "reason": "linked file"})
            else:
                candidates.append(path)
        if len(candidates) + len(skipped) >= 1000:
            skipped.append({"path": "(remaining files)", "reason": "scan limit reached"})
            break
    candidates.sort(key=lambda p: source_priority(p.relative_to(root).as_posix()))

    def read_candidates():
        for path in candidates[:1000]:
            try:
                with path.open("rb") as handle:
                    yield path.relative_to(root).as_posix(), handle.read(65537)
            except OSError:
                skipped.append({"path": path.relative_to(root).as_posix(), "reason": "unreadable file"})

    snapshot = collect_files(read_candidates())
    snapshot.skipped = skipped + snapshot.skipped
    return snapshot


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(scan_project(arguments.folder).manifest(), indent=2))
