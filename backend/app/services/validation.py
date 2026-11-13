"""Validation of uploaded CSV files.

Order of checks (cheapest and most fundamental first):
  extension -> size -> empty -> binary content -> encoding -> delimiter
  -> header -> row structure -> parse with pandas

Every rejection raises DatasetValidationError with a machine-readable code and
a message a person can understand. Nothing is silently dropped: recoverable
oddities (short rows, blank lines, Windows-1252 text) become warnings shown
to the user.
"""

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ALLOWED_DELIMITERS = ",;\t|"
SNIFF_CHARACTERS = 50_000
UTF8_BOM = b"\xef\xbb\xbf"
UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
DELIMITER_NAMES = {",": "comma", "\t": "tab", ";": "semicolon", "|": "pipe"}


class DatasetValidationError(Exception):
    """A user-facing problem with an uploaded file."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class UploadLimits:
    max_bytes: int
    max_rows: int
    max_columns: int


@dataclass
class ValidatedCSV:
    frame: pd.DataFrame
    encoding: str
    delimiter: str
    warnings: list[str] = field(default_factory=list)


def check_extension(filename: str) -> None:
    if not filename.lower().endswith(".csv"):
        raise DatasetValidationError(
            "unsupported_file_type",
            "Only .csv files are supported. Export your data as CSV and upload it again.",
            status_code=415,
        )


def decode_bytes(data: bytes) -> tuple[str, str, list[str]]:
    """Decode file bytes into text. Returns (text, encoding, warnings)."""
    if data.startswith(UTF8_BOM):
        return _decode_or_fail(data, "utf-8-sig"), "utf-8-sig", []
    if data.startswith(UTF16_BOMS):
        return _decode_or_fail(data, "utf-16"), "utf-16", []

    # Text files do not contain NUL bytes; images, Excel files and zips do.
    if b"\x00" in data[:65536]:
        raise DatasetValidationError(
            "not_a_text_file",
            "This file contains binary data, so it is not a CSV text file "
            "(it may be an Excel or other file renamed to .csv).",
            status_code=415,
        )
    try:
        return data.decode("utf-8"), "utf-8", []
    except UnicodeDecodeError:
        pass
    try:
        text = data.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise DatasetValidationError(
            "unsupported_encoding",
            "The file's text encoding is not supported. Save it as 'CSV UTF-8' and upload it again.",
        ) from exc
    return text, "cp1252", [
        "The file is not UTF-8, so it was read as Windows-1252 (common for Excel exports). "
        "If special characters look wrong, save the file as 'CSV UTF-8'."
    ]


def _decode_or_fail(data: bytes, encoding: str) -> str:
    try:
        return data.decode(encoding)
    except UnicodeDecodeError as exc:
        raise DatasetValidationError(
            "unsupported_encoding", f"The file is marked as {encoding} but could not be decoded."
        ) from exc


def detect_delimiter(text: str) -> str:
    """Guess the delimiter from the first part of the file; default to comma."""
    first_line = text.split("\n", 1)[0]
    try:
        delimiter = csv.Sniffer().sniff(text[:SNIFF_CHARACTERS], delimiters=ALLOWED_DELIMITERS).delimiter
    except csv.Error:
        delimiter = ","
    # A guessed delimiter that never appears in the header is not credible.
    if delimiter not in first_line and "," in first_line:
        return ","
    return delimiter


def _looks_numeric(value: str) -> bool:
    try:
        float(value.replace(",", ""))
        return True
    except ValueError:
        return False


def check_header(header: list[str], max_columns: int) -> list[str]:
    names = [name.strip() for name in header]
    if not any(names):
        raise DatasetValidationError("missing_header", "The first row is empty, so there are no column names.")
    empty_positions = [str(index + 1) for index, name in enumerate(names) if not name]
    if empty_positions:
        raise DatasetValidationError(
            "missing_header",
            f"Column(s) {', '.join(empty_positions)} have no name in the header row. Every column "
            "needs a name (also check for an extra delimiter at the end of each line).",
        )
    if len(names) > 1 and all(_looks_numeric(name) for name in names):
        raise DatasetValidationError(
            "missing_header",
            "The first row contains only numbers, so the file seems to have no header row. "
            "Add a first row with column names.",
        )
    seen = set()
    duplicates = set()
    for name in names:
        key = name.lower()
        if key in seen:
            duplicates.add(name)
        seen.add(key)
    if duplicates:
        raise DatasetValidationError(
            "duplicate_columns",
            "Column names must be unique (ignoring upper/lower case). Duplicated: "
            + ", ".join(sorted(duplicates)),
        )
    if len(names) > max_columns:
        raise DatasetValidationError(
            "too_many_columns",
            f"The file has {len(names)} columns; the limit is {max_columns}.",
            status_code=413,
        )
    return names


def check_row_structure(text: str, delimiter: str, column_count: int, max_rows: int) -> list[str]:
    """Walk every row once with the csv module to find structural problems."""
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    next(reader, None)  # skip header
    data_rows = 0
    short_rows = 0
    blank_rows = 0
    try:
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                blank_rows += 1
                continue
            data_rows += 1
            if data_rows > max_rows:
                raise DatasetValidationError(
                    "too_many_rows",
                    f"The file has more than {max_rows:,} data rows, the configured limit.",
                    status_code=413,
                )
            if len(row) > column_count:
                raise DatasetValidationError(
                    "malformed_csv",
                    f"Row {line_number} has {len(row)} fields but the header has {column_count}. "
                    "Check for unquoted delimiters inside values.",
                )
            if len(row) < column_count:
                short_rows += 1
    except csv.Error as exc:
        raise DatasetValidationError(
            "malformed_csv", "The file could not be read as CSV (check quoting)."
        ) from exc
    if data_rows == 0:
        raise DatasetValidationError("no_data_rows", "The file has a header but no data rows.")

    warnings = []
    if short_rows:
        warnings.append(
            f"{short_rows:,} row(s) have fewer fields than the header; the missing fields are treated as empty."
        )
    if blank_rows:
        warnings.append(f"{blank_rows:,} blank line(s) were ignored.")
    return warnings


def read_and_validate_csv(path: Path, limits: UploadLimits) -> ValidatedCSV:
    """Run every check on a stored file and return it as a DataFrame."""
    size = path.stat().st_size
    if size == 0:
        raise DatasetValidationError("empty_file", "The file is empty.")
    if size > limits.max_bytes:
        raise DatasetValidationError(
            "file_too_large",
            f"The file is {size / 1_048_576:.1f} MB; the limit is {limits.max_bytes / 1_048_576:.0f} MB.",
            status_code=413,
        )

    text, encoding, warnings = decode_bytes(path.read_bytes())
    if not text.strip():
        raise DatasetValidationError("empty_file", "The file contains only whitespace.")

    delimiter = detect_delimiter(text)
    header = next(csv.reader(io.StringIO(text), delimiter=delimiter), [])
    names = check_header(header, limits.max_columns)
    warnings += check_row_structure(text, delimiter, len(names), limits.max_rows)

    try:
        frame = pd.read_csv(io.StringIO(text), sep=delimiter, on_bad_lines="error", low_memory=False)
    except (pd.errors.ParserError, ValueError) as exc:
        raise DatasetValidationError(
            "malformed_csv", "The file could not be parsed as CSV. Check quoting and delimiters."
        ) from exc

    frame.columns = names
    if delimiter != ",":
        warnings.append(f"Detected {DELIMITER_NAMES[delimiter]}-separated values.")
    return ValidatedCSV(frame=frame, encoding=encoding, delimiter=delimiter, warnings=warnings)


def load_stored_csv(path: Path, encoding: str, delimiter: str) -> pd.DataFrame:
    """Re-read a file that already passed validation (used before each analysis)."""
    frame = pd.read_csv(path, sep=delimiter, encoding=encoding, low_memory=False)
    frame.columns = [str(name).strip() for name in frame.columns]
    return frame
