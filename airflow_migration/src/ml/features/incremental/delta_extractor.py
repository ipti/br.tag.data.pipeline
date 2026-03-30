from __future__ import annotations

import hashlib
import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

_FINGERPRINT_COLS = [
    "nota_final_norm",
    "nota_g1_norm",
    "nota_g2_norm",
    "total_faltas_abs",
    "taxa_ausencia",
    "aluno_reprovado_flag",
    "em_recuperacao",
]

_DEFAULT_RAW_DIR = Path(__file__).parent.parent.parent / "data" / "raw"


def _fingerprint_df(df: pd.DataFrame) -> pd.Series:
    """
    Compute a per-row MD5 hash of mutable fingerprint columns.

    Args:
        df (pd.DataFrame): DataFrame containing raw parsed structural data targeting extraction fields.

    Raises:
        Exception: If MD5 internal hashing encounters anomalous string types.

    Returns:
        pd.Series: Series object perfectly aligned with the original dataframe index containing hashes.
    """
    cols = [c for c in _FINGERPRINT_COLS if c in df.columns]
    combined = df[cols].fillna(-999).astype(str).agg("".join, axis=1)
    return combined.apply(lambda s: hashlib.md5(s.encode()).hexdigest())


def _load_existing_fingerprints(
    raw_dir: Path | None, segment: str, year: int, fs=None
) -> dict[str, str]:
    """
    Load mapping of student_id to fingerprint from existing year Parquet.

    Returns {} if no file exists (triggers full extraction for that year).

    Args:
        raw_dir (Path | None): Local base directory (ignored in Azure mode).
        segment (str): Grade segment (EF1/EF2).
        year (int): Extraction year.
        fs: adlfs filesystem instance (None → local mode).

    Returns:
        dict[str, str]: student_id → MD5 fingerprint.
    """
    if fs is not None:
        from src.ml.features._azure_storage import CONTAINER

        blob_key = (
            f"{CONTAINER}/raw/segment={segment}/year={year}/{segment}_{year}.parquet"
        )
        if not fs.exists(blob_key):
            logger.info(
                "No existing blob for %s year=%d — will do full extraction",
                segment,
                year,
            )
            return {}
        needed = ["student_id"] + _FINGERPRINT_COLS
        schema = pq.read_schema(blob_key, filesystem=fs)
        available = [c for c in needed if c in schema.names]
        df = pq.read_table(blob_key, columns=available, filesystem=fs).to_pandas()
    else:
        path = raw_dir / f"{segment}_{year}.parquet"  # type: ignore[operator]
        if not path.exists():
            logger.info(
                "No existing Parquet for %s year=%d — will do full extraction",
                segment,
                year,
            )
            return {}
        needed = ["student_id"] + _FINGERPRINT_COLS
        available = [c for c in needed if c in pq.read_schema(str(path)).names]
        df = pq.read_table(str(path), columns=available).to_pandas()

    fps = _fingerprint_df(df)
    return dict(zip(df["student_id"], fps))


def _load_existing_school_ids(
    raw_dir: Path | None, segment: str, year: int, fs=None
) -> set[str]:
    """
    Load existing school IDs from stored Parquet.

    Args:
        raw_dir (Path | None): Local base directory (ignored in Azure mode).
        segment (str): Grade segment.
        year (int): Year.
        fs: adlfs filesystem instance (None → local mode).

    Returns:
        set[str]: Set of existing school IDs.
    """
    if fs is not None:
        from src.ml.features._azure_storage import CONTAINER

        blob_key = (
            f"{CONTAINER}/raw/segment={segment}/year={year}/{segment}_{year}.parquet"
        )
        if not fs.exists(blob_key):
            return set()
        return set(
            pq.read_table(blob_key, columns=["school_id"], filesystem=fs)
            .column("school_id")
            .to_pylist()
        )
    else:
        path = raw_dir / f"{segment}_{year}.parquet"  # type: ignore[operator]
        if not path.exists():
            return set()
        return set(
            pq.read_table(str(path), columns=["school_id"])
            .column("school_id")
            .to_pylist()
        )


class DeltaExtractor:
    """
    Detects and extracts only new or changed students for open years.

    Supports Azure Blob Storage when the injected extractor has _azure=True.
    """

    def __init__(
        self, extractor, segment: str = "EF1", raw_dir: Path | None = None
    ) -> None:
        """
        Initialize the DeltaExtractor.

        Args:
            extractor: Live Neo4jExtractor instance.
            segment (str, optional): EF1 or EF2. Defaults to "EF1".
            raw_dir (Path | None, optional): Local Parquet dir (ignored in Azure mode).

        Returns:
            None
        """
        self._ext = extractor
        self._segment = segment
        self._azure: bool = getattr(extractor, "_azure", False)
        self._fs = getattr(extractor, "fs", None)

        if self._azure:
            from src.ml.features._azure_storage import CONTAINER

            self._container = CONTAINER
        else:
            self._raw_dir = raw_dir or _DEFAULT_RAW_DIR
            self._raw_dir.mkdir(parents=True, exist_ok=True)
            self._container = None

    def _year_blob_key(self, year: int) -> str:
        return (
            f"{self._container}/raw/segment={self._segment}"
            f"/year={year}/{self._segment}_{year}.parquet"
        )

    def extract_delta(
        self, current_years: list[int], run_date: date
    ) -> dict[int, str | Path | None]:
        """
        Compare extraction against existing Parquet stores, write delta, and upsert.

        Args:
            current_years (list[int]): Open years from the watermark.
            run_date (date): Run date used in delta file naming.

        Returns:
            dict[int, str | Path | None]: year → delta path (blob str or local Path), or None.
        """
        results: dict[int, str | Path | None] = {}

        for year in current_years:
            logger.info("[delta] year=%d segment=%s", year, self._segment)

            raw_dir_arg = None if self._azure else self._raw_dir
            existing_fps = _load_existing_fingerprints(
                raw_dir_arg, self._segment, year, fs=self._fs
            )
            existing_schools = _load_existing_school_ids(
                raw_dir_arg, self._segment, year, fs=self._fs
            )

            raw_path = self._ext.extract_students_base(self._segment, year=year)

            # Open the raw Parquet (blob or local)
            if self._azure:
                pf = pq.ParquetFile(raw_path, filesystem=self._fs)
            else:
                pf = pq.ParquetFile(str(raw_path))

            delta_batches: list[pd.DataFrame] = []
            for batch in pf.iter_batches(batch_size=200_000):
                df = batch.to_pandas()
                new_mask = ~df["student_id"].isin(existing_fps)
                current_fps = _fingerprint_df(df)
                changed_mask = df["student_id"].apply(
                    lambda sid: sid in existing_fps
                    and existing_fps[sid] != current_fps.get(sid, "")
                )
                chunk = df[new_mask | changed_mask]
                if not chunk.empty:
                    delta_batches.append(chunk)

            if not delta_batches:
                logger.info("[delta] year=%d: no changes", year)
                results[year] = None
                continue

            delta_df = pd.concat(delta_batches, ignore_index=True)

            new_schools = set(delta_df["school_id"].unique()) - existing_schools
            if new_schools:
                logger.info(
                    "[delta] year=%d: %d new schools: %s...",
                    year,
                    len(new_schools),
                    list(new_schools)[:5],
                )

            n_new = int((~delta_df["student_id"].isin(existing_fps)).sum())
            n_changed = len(delta_df) - n_new
            logger.info(
                "[delta] year=%d: %d new, %d changed students", year, n_new, n_changed
            )

            if self._azure:
                delta_key = (
                    f"{self._container}/raw/segment={self._segment}/year={year}"
                    f"/{self._segment}_{year}_delta_{run_date.isoformat()}.parquet"
                )
                delta_tbl = pa.Table.from_pandas(delta_df, preserve_index=False)
                pq.write_table(
                    delta_tbl, delta_key, filesystem=self._fs, compression="snappy"
                )
                results[year] = delta_key
            else:
                delta_path = (
                    self._raw_dir
                    / f"{self._segment}_{year}_delta_{run_date.isoformat()}.parquet"
                )
                delta_df.to_parquet(str(delta_path), index=False, compression="snappy")
                results[year] = delta_path

            self._upsert_into_year(year, delta_df)

        return results

    def _upsert_into_year(self, year: int, delta_df: pd.DataFrame) -> None:
        """
        Upsert delta rows back into the year Parquet (blob or local).

        Azure: write to a tmp blob key, delete original, server-side copy.
        Local: write to a .tmp.parquet, then atomic replace.

        Args:
            year (int): Year to upsert into.
            delta_df (pd.DataFrame): New/changed rows.
        """
        delta_ids = set(delta_df["student_id"].tolist())
        delta_tbl = pa.Table.from_pandas(delta_df, preserve_index=False)

        if self._azure:
            year_key = self._year_blob_key(year)
            tmp_key = year_key.replace(".parquet", "_tmp.parquet")

            if not self._fs.exists(year_key):
                pq.write_table(
                    delta_tbl, year_key, filesystem=self._fs, compression="snappy"
                )
                logger.info(
                    "[upsert] Created blob %s (%d rows)", year_key, len(delta_df)
                )
                return

            writer: pq.ParquetWriter | None = None
            pf = pq.ParquetFile(year_key, filesystem=self._fs)
            try:
                for batch in pf.iter_batches(batch_size=200_000):
                    df = batch.to_pandas()
                    df = df[~df["student_id"].isin(delta_ids)]
                    if df.empty:
                        continue
                    tbl = pa.Table.from_pandas(df, preserve_index=False)
                    if writer is None:
                        writer = pq.ParquetWriter(
                            tmp_key,
                            tbl.schema,
                            filesystem=self._fs,
                            compression="snappy",
                        )
                    writer.write_table(tbl)

                if writer is None:
                    writer = pq.ParquetWriter(
                        tmp_key,
                        delta_tbl.schema,
                        filesystem=self._fs,
                        compression="snappy",
                    )
                writer.write_table(delta_tbl)
            finally:
                if writer:
                    writer.close()

            # Server-side copy — O(1) on Azure (no data transfer)
            self._fs.rm(year_key)
            self._fs.copy(tmp_key, year_key)
            self._fs.rm(tmp_key)
            logger.info(
                "[upsert] Updated blob %s (+%d rows upserted)", year_key, len(delta_df)
            )

        else:
            year_path = self._raw_dir / f"{self._segment}_{year}.parquet"
            tmp_path = year_path.with_suffix(".tmp.parquet")

            if not year_path.exists():
                pq.write_table(delta_tbl, str(year_path), compression="snappy")
                logger.info(
                    "[upsert] Created %s (%d rows)", year_path.name, len(delta_df)
                )
                return

            writer = None
            pf = pq.ParquetFile(str(year_path))
            try:
                for batch in pf.iter_batches(batch_size=200_000):
                    df = batch.to_pandas()
                    df = df[~df["student_id"].isin(delta_ids)]
                    if df.empty:
                        continue
                    tbl = pa.Table.from_pandas(df, preserve_index=False)
                    if writer is None:
                        writer = pq.ParquetWriter(
                            str(tmp_path), tbl.schema, compression="snappy"
                        )
                    writer.write_table(tbl)

                if writer is None:
                    writer = pq.ParquetWriter(
                        str(tmp_path), delta_tbl.schema, compression="snappy"
                    )
                writer.write_table(delta_tbl)
            finally:
                if writer:
                    writer.close()

            tmp_path.replace(year_path)
            logger.info(
                "[upsert] Updated %s (+%d rows upserted)", year_path.name, len(delta_df)
            )
