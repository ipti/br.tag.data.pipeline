from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

# Suppress verbose per-request HTTP logs from the Azure SDK (request headers,
# response headers, etc.). Only warnings and errors will surface.
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.storage").setLevel(logging.WARNING)

if TYPE_CHECKING:
    import adlfs

CONTAINER = "machine-learning"


def is_configured() -> bool:
    """Return True when Azure env vars are present."""
    return bool(os.environ.get("AZURE_STORAGE_ACCOUNT_NAME"))


def get_storage_options() -> dict:
    """Return kwargs for adlfs / PyArrow storage_options."""
    return {
        "account_name": os.environ["AZURE_STORAGE_ACCOUNT_NAME"],
        "account_key": os.environ["AZURE_STORAGE_ACCOUNT_KEY"],
    }


def get_fs() -> "adlfs.AzureBlobFileSystem":
    """Return an authenticated adlfs filesystem."""
    import adlfs

    return adlfs.AzureBlobFileSystem(**get_storage_options())


def fs_path(key: str) -> str:
    """adlfs-compatible path: container/key  (no az:// prefix)."""
    return f"{CONTAINER}/{key}"


def az_url(key: str) -> str:
    """az:// URL for logging / display."""
    return f"az://{CONTAINER}/{key}"


def raw_blob_key(segment: str, year: int, filename: str) -> str:
    """Partitioned raw path: raw/segment={segment}/year={year}/{filename}"""
    return f"raw/segment={segment}/year={year}/{filename}"


def feature_blob_key(segment: str, year: int, run_date_nodash: str, kind: str) -> str:
    """Partitioned features path: features/segment=.../year=.../run=.../{kind}.parquet"""
    return f"features/segment={segment}/year={year}/run={run_date_nodash}/{kind}.parquet"
