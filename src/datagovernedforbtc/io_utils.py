from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from pathlib import Path
from typing import Iterable


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv_rows_from_path(path: Path) -> tuple[list[str], Iterable[dict[str, str]], str | None]:
    """Return header, rows iterable, inner file name for .csv or single-csv .zip."""
    if path.suffix.lower() == ".zip":
        zf = zipfile.ZipFile(path)
        names = [n for n in zf.namelist() if not n.endswith("/")]
        csv_names = [n for n in names if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError(f"zip has no csv member: {path}")
        inner = csv_names[0]
        data = zf.read(inner).decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(data))
        return list(reader.fieldnames or []), list(reader), inner
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader), None


def write_csv_rows(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_parquet_rows(path: Path, rows: list[dict]) -> None:
    """Write rows to Parquet with pyarrow via pandas.

    Parquet is the preferred long-term Feature/Normalized storage format.
    The caller should fail loudly if pyarrow/pandas are unavailable; silently
    writing CSV with a .parquet suffix would be a data-governance violation.
    """
    if not rows:
        raise ValueError("cannot write empty parquet rows")
    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover - environment-specific
        raise RuntimeError("pandas is required for parquet output") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False, engine="pyarrow")
