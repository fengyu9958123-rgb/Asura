"""
Shared task identity resolver.

The UI can enter a task detail page with different ids:
- text PRD id
- text runtime task id
- image requirement module id
- image runtime task id

Routes must normalize those ids before reading task state, confirmation items,
results, or files. Keeping the logic here prevents each endpoint from making a
slightly different guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from database.models import PRD, RequirementModule, Task, db_manager


@dataclass(frozen=True)
class TaskIdentity:
    requested_id: str
    kind: str
    task_id: Optional[str] = None
    prd_id: Optional[str] = None
    module_id: Optional[str] = None
    module_task_id: Optional[str] = None

    @property
    def is_text(self) -> bool:
        return self.kind == "text"

    @property
    def is_image(self) -> bool:
        return self.kind == "image"

    @property
    def canonical_id(self) -> str:
        return self.task_id or self.module_task_id or self.module_id or self.requested_id


def resolve_task_identity(identifier: str) -> TaskIdentity:
    """Resolve any supported task reference to its canonical runtime identity."""
    identifier = str(identifier or "")
    session = db_manager.get_session()
    try:
        task = session.query(Task).filter_by(id=identifier).first()
        if task:
            if task.prd_id and str(task.prd_id).startswith("req_mod_"):
                module = session.query(RequirementModule).filter_by(id=task.prd_id).first()
                return _image_identity(identifier, module, fallback_task_id=task.id)
            return TaskIdentity(
                requested_id=identifier,
                kind="text",
                task_id=task.id,
                prd_id=task.prd_id,
            )

        module = _find_module(session, identifier)
        if module:
            return _image_identity(identifier, module)

        prd = session.query(PRD).filter_by(id=identifier).first()
        if prd:
            task_id = _latest_text_task_id(session, prd)
            return TaskIdentity(
                requested_id=identifier,
                kind="text",
                task_id=task_id,
                prd_id=prd.id,
            )

        return TaskIdentity(requested_id=identifier, kind="unknown")
    finally:
        session.close()


def resolve_text_task_id(identifier: str) -> str:
    identity = resolve_task_identity(identifier)
    return identity.task_id or str(identifier or "")


def resolve_runtime_task_id(identifier: str) -> str:
    identity = resolve_task_identity(identifier)
    return identity.canonical_id


def _find_module(session, identifier: str) -> Optional[RequirementModule]:
    if identifier.startswith("req_mod_"):
        return session.query(RequirementModule).filter_by(id=identifier).first()

    return (
        session.query(RequirementModule)
        .filter(
            (RequirementModule.generated_task_id == identifier)
            | (RequirementModule.task_id == identifier)
        )
        .first()
    )


def _image_identity(
    requested_id: str,
    module: Optional[RequirementModule],
    fallback_task_id: Optional[str] = None,
) -> TaskIdentity:
    if not module:
        return TaskIdentity(requested_id=requested_id, kind="unknown")

    module_task_id = module.task_id or module.generated_task_id or fallback_task_id
    return TaskIdentity(
        requested_id=requested_id,
        kind="image",
        task_id=fallback_task_id,
        prd_id=module.id,
        module_id=module.id,
        module_task_id=module_task_id,
    )


def _latest_text_task_id(session, prd: PRD) -> Optional[str]:
    if prd.generated_task_id:
        task = session.query(Task).filter_by(id=prd.generated_task_id).first()
        if task:
            return task.id

    task = (
        session.query(Task)
        .filter_by(prd_id=prd.id)
        .order_by(Task.updated_at.desc())
        .first()
    )
    return task.id if task else None
