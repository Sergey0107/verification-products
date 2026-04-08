from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record_audit_event(
    db: Session,
    *,
    project_key: str = "shared",
    entity_type: str,
    entity_id: str,
    action: str,
    snapshot: dict[str, Any],
    actor: str = "system",
) -> None:
    db.add(
        AuditEvent(
            project_key=project_key,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            snapshot_json=snapshot,
        )
    )
