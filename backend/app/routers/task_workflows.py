"""Authenticated task-workflow compilation endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app import models
from app.auth import get_current_user
from app.response import ok
from app.task_workflows import TaskWorkflowCompileRequest, compile_task_workflow, workflow_catalog

router = APIRouter(prefix="/task-workflows", tags=["task-workflows"])


@router.get("/catalog")
def get_catalog(
    _current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Expose workflow definitions to an authenticated caller without creating a run."""
    return ok(workflow_catalog().model_dump(mode="json"))


@router.post("/compile")
def compile_workflow(
    request: TaskWorkflowCompileRequest,
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Bind a compiled plan to the authenticated user; compilation is not execution approval."""
    contract = compile_task_workflow(current_user.id, request)
    return ok(contract.model_dump(mode="json"))


__all__ = ["router"]
