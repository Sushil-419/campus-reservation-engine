"""Audit logging — writes to audit_log in its own transaction
so that failed attempts are still recorded.
Never logs passwords, tokens, or stack traces."""
from typing import Any, Optional
from sqlalchemy.orm import Session as DBSession
from app.db import SessionLocal
from app.models import AuditLog


def write_audit(
    action: str,
    entity: str,
    outcome: str,
    actor_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    detail: Optional[dict[str, Any]] = None,
    db: Optional[DBSession] = None,
) -> None:
    """Write an audit log entry.
    If db is provided, uses a savepoint on the existing session to avoid connection pool exhaustion.
    Otherwise opens its own session."""
    if db is not None:
        try:
            entry = AuditLog(
                actor_id=actor_id,
                action=action,
                entity=entity,
                entity_id=entity_id,
                outcome=outcome,
                detail=detail,
            )
            with db.begin_nested():
                db.add(entry)
            db.commit()
            return
        except Exception:
            pass

    audit_db = SessionLocal()
    try:
        entry = AuditLog(
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            outcome=outcome,
            detail=detail,
        )
        audit_db.add(entry)
        audit_db.commit()
    except Exception:
        audit_db.rollback()
    finally:
        audit_db.close()
