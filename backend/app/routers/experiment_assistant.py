"""Conversation-to-draft compiler endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app import experiment_assistant, models, schemas
from app.auth import get_current_user
from app.response import ok
from app.task_workflows import (
    TaskWorkflowCompileRequest,
    WorkflowContextItem,
    compile_task_workflow,
)

router = APIRouter(prefix="/experiment-assistant", tags=["experiment-assistant"])


@router.post("/turn")
async def compile_turn(
    request: schemas.ExperimentAssistantTurnRequest,
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Compile one ordinary-language turn into validated draft patches.

    This route is deliberately draft-only. It cannot create a Job, start a
    simulator, or mutate persisted experiment state.
    """

    current_values = json.dumps(
        request.current_values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    workflow_request = TaskWorkflowCompileRequest(
        request_id=f"assistant:{hashlib.sha256(request.message_id.encode()).hexdigest()[:32]}",
        edition=request.edition,
        requested_task_type=request.requested_task_type,
        message=request.message,
        locale=request.locale,
        conversation_summary=request.conversation_summary,
        context=[
            WorkflowContextItem(
                key="assistant.current_values",
                value=current_values[:4_000],
                source="workspace",
            ),
        ],
        requested_tool_ids=[],
    )
    workflow = compile_task_workflow(current_user.id, workflow_request)
    if workflow.task_type != "control_tuning":
        step_summary = " → ".join(step.title for step in workflow.steps)
        if request.locale == "zh-CN":
            summary = f"已生成 {workflow.task_type} 工作流：{step_summary}"
            if workflow.blockers:
                summary += f"。当前阻塞：{'；'.join(workflow.blockers)}"
        else:
            summary = f"Compiled {workflow.task_type} workflow: {step_summary}"
            if workflow.blockers:
                summary += f". Current blockers: {'; '.join(workflow.blockers)}"
        response = schemas.ExperimentAssistantTurnResponse(
            experiment_summary=summary[:2_000],
            accepted_patches=[],
            rejected_patches=[],
            accepted_parameter_patches=[],
            rejected_parameter_patches=[],
            missing_field_ids=[],
            review_field_ids=[],
            questions=[],
            usage=schemas.ExperimentAssistantUsage(),
            provider="dronedream-workflow-compiler",
            model=workflow.system_prompt_version,
            assistant_message=summary[:4_000],
            orchestration={
                "run_id": workflow.contract_id,
                "conversation_id": f"conversation:{workflow.contract_sha256[:24]}",
                "tenant_id": workflow.owner_binding_sha256,
                "organization_id": None,
                "workspace_id": f"workflow:{workflow.contract_id}",
                "edition": workflow.edition,
                "artifact_id": workflow.contract_id,
                "artifact_version": 1,
                "product_link": workflow.product_path,
                "artifact_kind": workflow.artifact_kind,
                "artifact_payload": workflow.model_dump(mode="json"),
                "sequence": 1,
                "intent": workflow.task_type,
                "workflow": [
                    {
                        "step": step.step_id,
                        "label": step.title,
                        "status": "needs_input" if workflow.status == "blocked" else "completed",
                    }
                    for step in workflow.steps
                ],
            },
        )
        return ok(response.model_dump(mode="json"))
    if request.llm is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MODEL_ACCESS_REQUIRED",
                "message": "Control tuning requires an approved model-access configuration.",
            },
        )
    try:
        result = await asyncio.to_thread(
            experiment_assistant.compile_experiment_turn,
            request,
        )
    except experiment_assistant.ExperimentAssistantError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return ok(result.model_dump(mode="json"))


__all__ = ["router"]
