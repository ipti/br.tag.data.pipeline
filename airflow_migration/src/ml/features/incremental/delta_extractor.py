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
    raw_dir: Path, segment: str, year: int
) -> dict[str, str]:
    """
    Load mapping of student_id to fingerprint from existing year Parquet file.

    Reads only fingerprint columns without loading full datasets into RAM.
    Returns {} if no file exists (triggers full extraction for that year).

    Args:
        raw_dir (Path): Base pathlib location tracking where generated Parquet outputs land.
        segment (str): Grade grouping segment tracking.
        year (int): Specific numeric active parsing year constraints.

    Raises:
        Exception: Failure parsing PyArrow schema.

    Returns:
        dict[str, str]: Dictionary relating structural 'student_id' fields against cached MD5 hashes.
    """
    path = raw_dir / f"{segment}_{year}.parquet"
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


def _load_existing_school_ids(raw_dir: Path, segment: str, year: int) -> set[str]:
    """
    Load existing school IDs out of stored base Parquet archives safely.

    Args:
        raw_dir (Path): Base directory tracking stored outputs.
        segment (str): Grade configuration segment identifier.
        year (int): Numerical year binding explicit scopes.

    Raises:
        Exception: Issues reading internal parquets utilizing PyArrow IO constraints.

    Returns:
        set[str]: Set holding loaded existing school string structural identities.
    """
    path = raw_dir / f"{segment}_{year}.parquet"
    if not path.exists():
        return set()
    return set(
        pq.read_table(str(path), columns=["school_id"]).column("school_id").to_pylist()
    )


class DeltaExtractor:
    """
    Detects and extracts only new or changed students for open years.
    """

    def __init__(
        self, extractor, segment: str = "EF1", raw_dir: Path | None = None
    ) -> None:
        """
        Initialize the DeltaExtractor.

        Args:
            extractor: Live initialized extracting instance querying explicit graph logic loops.
            segment (str, optional): Bounds defining extraction segment blocks. Defaults to "EF1".
            raw_dir (Path | None, optional): Parquet storage directory constraint. Defaults to None.

        Raises:
            Exception: If directory creation fails due to filesystem permissions.

        Returns:
            None
        """
        self._ext = extractor
        self._segment = segment
        self._raw_dir = raw_dir or _DEFAULT_RAW_DIR
        self._raw_dir.mkdir(parents=True, exist_ok=True)

    def extract_delta(
        self, current_years: list[int], run_date: date
    ) -> dict[int, Path | None]:
        """
        Compare extraction against existing Parquet stores, write delta, and upsert.

        Args:
            current_years (list[int]): Years marked open internally inside specific temporal watermark logic loops.
            run_date (date): Tracking active parsing runtime instances structurally.

        Raises:
            Exception: Failure points bubbling upwards directly matching batch PyArrow limits.

        Returns:
            dict[int, Path | None]: Dictionary relating modified explicit year logic to valid Path targets.
        """
        results: dict[int, Path | None] = {}

        for year in current_years:
            logger.info("[delta] year=%d segment=%s", year, self._segment)

            existing_fps = _load_existing_fingerprints(
                self._raw_dir, self._segment, year
            )
            existing_schools = _load_existing_school_ids(
                self._raw_dir, self._segment, year
            )

            # Full Neo4j extraction for this year (uses paginated school-by-school)
            raw_path = self._ext.extract_students_base(self._segment, year=year)

            delta_batches: list[pd.DataFrame] = []
            pf = pq.ParquetFile(str(raw_path))

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

            # Observability: log new schools
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
        Upsert delta rows cleanly directly straight back within structural year Parquets.

        Reads existing files iteratively safely bypassing limits.

        Args:
            year (int): Numeric identifier targeting specific storage block bounds.
            delta_df (pd.DataFrame): Dataframe tracking only new or actively changed states inherently.

        Raises:
            Exception: Thrown against blocked file replacements via temporary writing operations.

        Returns:
            None
        """
        year_path = self._raw_dir / f"{self._segment}_{year}.parquet"
        tmp_path = year_path.with_suffix(".tmp.parquet")
        delta_ids = set(delta_df["student_id"].tolist())
        delta_tbl = pa.Table.from_pandas(delta_df, preserve_index=False)

        if not year_path.exists():
            pq.write_table(delta_tbl, str(year_path), compression="snappy")
            logger.info("[upsert] Created %s (%d rows)", year_path.name, len(delta_df))
            return

        writer: pq.ParquetWriter | None = None
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
