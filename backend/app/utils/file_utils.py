"""Safe handling of user-supplied file names and stored file paths."""

import re
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._ ()\-]+")
_STORED_NAME = re.compile(r"[0-9a-f]{32}\.csv")
MAX_DISPLAY_NAME_LENGTH = 120


def safe_display_name(original_name: str | None) -> str:
    """Return a harmless version of the uploaded file's name, for display only.

    The name is never used to build a path on disk: a browser can send names
    such as "../../secret.csv" or "C:\\Windows\\x.csv".
    """
    if not original_name:
        return "upload.csv"
    # Keep only the last path component, whether the client used / or \.
    name = PureWindowsPath(PurePosixPath(original_name).name).name
    name = _UNSAFE_CHARS.sub("_", name).strip(" .")
    return (name or "upload.csv")[:MAX_DISPLAY_NAME_LENGTH]


def generate_stored_filename() -> str:
    """Random server-side file name, so users never control paths on disk."""
    return f"{uuid.uuid4().hex}.csv"


def resolve_stored_path(upload_dir: Path, stored_filename: str) -> Path:
    """Build the path of a stored upload, refusing anything outside upload_dir."""
    if not _STORED_NAME.fullmatch(stored_filename):
        raise ValueError("Invalid stored file name")
    base = upload_dir.resolve()
    path = (base / stored_filename).resolve()
    if path.parent != base:
        raise ValueError("Stored file path escapes the upload directory")
    return path
