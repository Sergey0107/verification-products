from uuid import UUID

from fastapi import HTTPException


def parse_uuid(value: str | None, *, detail: str = "Invalid id") -> UUID:
    """Parse a path/body string into a UUID, raising HTTP 400 on failure."""
    try:
        return UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail=detail)
