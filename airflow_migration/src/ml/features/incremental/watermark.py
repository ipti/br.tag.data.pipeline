from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

YEAR_CLOSE_AFTER_DAYS: int = 60

_DEFAULT_CHECKPOINT_DIR = Path(__file__).parent.parent.parent / "data" / "checkpoints"


class Watermark:
    """
    Manages active mutable extraction windows defining 'open' and 'closed' years safely.
    """

    def __init__(self, checkpoint_dir: Path | None = None) -> None:
        """
        Initialize the Watermark state.

        Args:
            checkpoint_dir (Path | None, optional): Explicit target structural logic mapping bounds. Defaults to None.

        Raises:
            Exception: If directory creation encounters IO permission bounds.

        Returns:
            None
        """
        self._path = (checkpoint_dir or _DEFAULT_CHECKPOINT_DIR) / "watermark.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> dict:
        """
        Load internal serialization structural bounds directly from existing saved footprints.

        Args:
            None

        Raises:
            Exception: Failure explicitly against json loading execution parameters.

        Returns:
            dict: Parsed base standard mapping defaults.
        """
        if self._path.exists():
            with open(self._path) as f:
                state = json.load(f)
            logger.info("Watermark loaded: %s", state)
            return state
        cal = date.today().year
        return {
            "last_run_date": None,
            "current_years": [cal - 1, cal],
            "closed_years": [],
            "year_last_delta": {},
        }

    def save(self) -> None:
        """
        Save active parsed serialization footprints correctly against designated state trackers.

        Args:
            None

        Raises:
            Exception: Overwrite exceptions triggering safely per standard Python open limits.

        Returns:
            None
        """
        with open(self._path, "w") as f:
            json.dump(self._state, f, indent=2, default=str)

    @property
    def last_run_date(self) -> date | None:
        raw = self._state.get("last_run_date")
        return date.fromisoformat(raw) if raw else None

    @property
    def current_years(self) -> list[int]:
        return list(self._state["current_years"])

    @property
    def closed_years(self) -> list[int]:
        return list(self._state["closed_years"])

    def mark_run(self, run_date: date, years_with_delta: list[int]) -> None:
        """
        Record a successful extraction run while updating internal active year windows dynamically.

        Updates last_run_date, records activity directly against specific years actively modifying closing periods.

        Args:
            run_date (date): Precise execution boundary marking run targets accurately.
            years_with_delta (list[int]): Numeric keys isolating which exact years explicitly received new changes dynamically.

        Raises:
            Exception: Throws safely during generic list operation blocks conditionally.

        Returns:
            None
        """
        self._state["last_run_date"] = run_date.isoformat()

        for yr in years_with_delta:
            self._state["year_last_delta"][str(yr)] = run_date.isoformat()

        # Ensure current calendar year is tracked
        cal = run_date.year
        if (
            cal not in self._state["current_years"]
            and cal not in self._state["closed_years"]
        ):
            self._state["current_years"].append(cal)
            logger.info("New calendar year %d added to current_years", cal)

        # Promote years with no delta for YEAR_CLOSE_AFTER_DAYS to closed
        cutoff = run_date - timedelta(days=YEAR_CLOSE_AFTER_DAYS)
        for yr in list(self._state["current_years"]):
            last_str = self._state["year_last_delta"].get(str(yr))
            should_close = (last_str is None and yr < run_date.year - 1) or (
                last_str is not None and date.fromisoformat(last_str) < cutoff
            )
            if should_close:
                self._state["current_years"].remove(yr)
                self._state["closed_years"].append(yr)
                logger.info(
                    "Year %d closed (no delta for >%d days)", yr, YEAR_CLOSE_AFTER_DAYS
                )

        self.save()
