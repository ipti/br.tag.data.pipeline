# Incremental Feature Extraction

This directory contains logic for delta extraction and watermark management.

## delta_extractor.py
Delta extraction layer.

Compares the existing Parquet for each open year against a fresh Neo4j query and returns only rows that are new or changed. Supports both local filesystem and Azure Blob Storage via adlfs.

"Changed" detection strategy:
Neo4j has no `updated_at` on Student nodes. Instead we use a composite fingerprint of the mutable fields (notas, faltas, situacao) hashed per student_id. Any student whose fingerprint differs from the stored Parquet is included in the delta.

Fingerprint columns (mutable during the year):
`nota_final_norm`, `nota_g1_norm`, `nota_g2_norm`, `total_faltas_abs`, `taxa_ausencia`, `aluno_reprovado_flag`, `em_recuperacao`

- New student: student_id present in Neo4j but absent from existing Parquet.
- New school: school_id present in Neo4j but absent from existing Parquet (all students from that school treated as new).

**Azure Blob Storage support:**
DeltaExtractor detects Azure mode via the injected `extractor` object's `fs` attribute. When in Azure mode:
- `_load_existing_fingerprints` and `_load_existing_school_ids` accept an `fs` parameter (adlfs filesystem instance).
- Blob paths follow the pattern: `machine-learning/raw/segment={EF1|EF2}/year={YYYY}/{segment}_{year}.parquet`
- Files are read using PyArrow's `filesystem` API with blob existence checks via `fs.exists()`.

**Return value:**
`extract_delta` returns `dict[int, str | Path | None]`:
- Azure mode: str representing the blob key (`machine-learning/raw/segment={EF1|EF2}/year={YYYY}/{segment}_{year}_delta_{run_date}.parquet`)
- Local mode: Path object pointing to the delta Parquet file
- None: if no changes detected for that year

**Azure upsert logic:**
In Azure mode, upserting into the year Parquet follows a write-delete-copy pattern:
1. Write updated data to a temporary blob key (`{original}.parquet` → `{original}_tmp.parquet`)
2. Delete the original blob
3. Server-side copy from tmp to original (O(1) Azure operation, no data transfer)
4. Delete tmp blob

This avoids atomicity issues for non-concurrent educational data updates.

## watermark.py
Watermark manager for incremental feature extraction.

Tracks which years are still "open" (mutable, re-extracted daily) vs "closed" (immutable, never re-extracted). A year is closed automatically after `YEAR_CLOSE_AFTER_DAYS` with no new delta rows for that year. Supports dual storage backends: Azure Blob Storage and local filesystem.

**Storage backend detection:**
`Watermark.__init__` detects Azure mode via `_azure_storage.is_configured()`. If Azure is configured, it reads/writes the watermark to blob storage; otherwise it uses local filesystem.

**Azure mode:**
- Reads/writes via `adlfs.AzureBlobFileSystem.open()` at: `machine-learning/checkpoints/watermark.json`
- On first run: catches `FileNotFoundError` and initializes with default state (current_years = [today.year - 1, today.year])
- Subsequent runs: deserializes JSON from blob

**Local mode:**
- Original behavior unchanged
- Reads/writes at: `src/ml/data/checkpoints/watermark.json`

File: `src/ml/data/checkpoints/watermark.json` (local) or `machine-learning/checkpoints/watermark.json` (Azure)
Schema:
```json
{
  "last_run_date":  "2026-03-03",
  "current_years":  [2025, 2026],
  "closed_years":   [2023, 2024],
  "year_last_delta": {"2025": "2026-01-15", "2026": "2026-03-03"}
}
```
