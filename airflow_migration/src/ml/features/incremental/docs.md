# Incremental Feature Extraction

This directory contains logic for delta extraction and watermark management.

## delta_extractor.py
Delta extraction layer.

Compares the existing Parquet for each open year against a fresh Neo4j query and returns only rows that are new or changed.

"Changed" detection strategy:
Neo4j has no `updated_at` on Student nodes. Instead we use a composite fingerprint of the mutable fields (notas, faltas, situacao) hashed per student_id. Any student whose fingerprint differs from the stored Parquet is included in the delta.

Fingerprint columns (mutable during the year):
`nota_final_norm`, `nota_g1_norm`, `nota_g2_norm`, `total_faltas_abs`, `taxa_ausencia`, `aluno_reprovado_flag`, `em_recuperacao`

- New student: student_id present in Neo4j but absent from existing Parquet.
- New school: school_id present in Neo4j but absent from existing Parquet (all students from that school treated as new).

Output: one delta Parquet per year at:
`src/ml/data/raw/<segment>_<year>_delta_<run_date>.parquet`

## watermark.py
Watermark manager for incremental feature extraction.

Tracks which years are still "open" (mutable, re-extracted daily) vs "closed" (immutable, never re-extracted). A year is closed automatically after `YEAR_CLOSE_AFTER_DAYS` with no new delta rows for that year.

File: `src/ml/data/checkpoints/watermark.json`
Schema:
```json
{
  "last_run_date":  "2026-03-03",
  "current_years":  [2025, 2026],
  "closed_years":   [2023, 2024],
  "year_last_delta": {"2025": "2026-01-15", "2026": "2026-03-03"}
}
```
