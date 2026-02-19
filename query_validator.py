"""
Input validation for MCP tool arguments.

All external input (from Claude or the user) passes through these models
before any API call is made. Invalid input raises ValueError with a
user-friendly message — never a stack trace.

Security rules enforced here:
  - Technician names: letters, spaces, hyphens only (blocks injection attempts)
  - Date ranges: max 90 days, chronological order
  - No raw user strings ever reach a query parameter without passing through here
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_DATE_RANGE_DAYS = 90
_NAME_PATTERN = re.compile(r"^[A-Za-z\s\-]+$")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DateRangeQuery(BaseModel):
    """
    Validated date range for business-wide queries (no technician required).

    Date handling:
      - If neither start_date nor end_date is given → last full week (Mon–Sun)
      - If only start_date is given → single day
      - If only end_date is given → 7 days ending on end_date
      - If both are given → that range (max 90 days)

    Used directly by: get_revenue_summary, get_no_charge_jobs, compare_technicians.
    Extended by: TechnicianJobQuery (adds technician name).
    """

    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _parse_date(cls, v: object) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v).strip())
        except ValueError:
            raise ValueError(f"Invalid date {v!r} — use YYYY-MM-DD format")

    @model_validator(mode="after")
    def _validate_range(self) -> "DateRangeQuery":
        start, end = self._resolved_range()
        if (end - start).days > _MAX_DATE_RANGE_DAYS:
            raise ValueError(
                f"Date range is too large ({(end - start).days} days). "
                f"Maximum is {_MAX_DATE_RANGE_DAYS} days."
            )
        return self

    def _resolved_range(self) -> tuple[date, date]:
        """Return (start, end) applying defaults when fields are None."""
        today = date.today()

        if self.start_date is None and self.end_date is None:
            # Default: last full Mon–Sun week
            days_since_monday = today.weekday()  # 0=Mon … 6=Sun
            last_monday = today - timedelta(days=days_since_monday + 7)
            return last_monday, last_monday + timedelta(days=6)

        if self.start_date is not None and self.end_date is None:
            return self.start_date, self.start_date

        if self.start_date is None and self.end_date is not None:
            return self.end_date - timedelta(days=6), self.end_date

        start = self.start_date  # type: ignore[assignment]
        end = self.end_date  # type: ignore[assignment]

        if start > end:
            raise ValueError("start_date must be on or before end_date")

        return start, end

    def get_date_range(self) -> tuple[date, date]:
        """Return the resolved (start, end) date range for this query."""
        return self._resolved_range()


class TechnicianJobQuery(DateRangeQuery):
    """
    Validated input for technician-specific queries.

    Extends DateRangeQuery with a required technician name field.
    Used by: get_technician_jobs, get_technician_revenue.
    """

    technician_name: str = Field(..., min_length=1, max_length=100)

    @field_validator("technician_name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Technician name cannot be empty")
        if not _NAME_PATTERN.match(v):
            raise ValueError(
                "Technician name may only contain letters, spaces, and hyphens"
            )
        return v


class TechnicianNameQuery(BaseModel):
    """Validated technician name lookup — used by list_technicians and fuzzy matching."""

    name_fragment: str = Field(default="", max_length=100)

    @field_validator("name_fragment")
    @classmethod
    def _validate_fragment(cls, v: str) -> str:
        v = v.strip()
        if v and not _NAME_PATTERN.match(v):
            raise ValueError(
                "Search text may only contain letters, spaces, and hyphens"
            )
        return v



class JobsByTypeQuery(DateRangeQuery):
    """
    Validated input for job-type queries.

    Fields:
      - job_types: required comma-separated job type names (exact match expected)
      - technician_name: optional technician name fragment
      - status: Optional filter: "Completed", "Canceled", or "All"
    """

    job_types: str = Field(..., min_length=1, max_length=200)
    technician_name: str | None = Field(default=None, max_length=100)
    status: str = Field(default="All")

    @field_validator("job_types")
    @classmethod
    def _validate_job_types(cls, v: str) -> str:
        v = str(v).strip()
        if not v:
            raise ValueError("job_types cannot be empty — provide one or more job type names")
        return v

    @field_validator("technician_name")
    @classmethod
    def _validate_technician_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if v and not _NAME_PATTERN.match(v):
            raise ValueError("Technician name may only contain letters, spaces, and hyphens")
        return v

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        allowed = {"Completed", "Canceled", "All"}
        v = str(v).strip()
        if v not in allowed:
            raise ValueError('status must be one of: Completed, Canceled, All')
        return v

    def job_type_list(self) -> list[str]:
        """Return cleaned list of job type names (trimmed)."""
        parts = [p.strip() for p in self.job_types.split(",")]
        return [p for p in parts if p]
