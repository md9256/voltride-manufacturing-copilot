"""Proposed actions: view, confirm (the only ERP write path), reject.

The LLM has no route here: proposals are executed only by these endpoints,
called by the user's browser when they press Confirm.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import ClientId, Db
from app.odoo import OdooClient, get_odoo_client
from app.schemas.actions import ActionView
from app.services import actions

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("/{action_id}", response_model=ActionView)
async def get_action(action_id: str, db: Db, client_id: ClientId) -> ActionView:
    try:
        return actions.to_view(await actions.get_action(db, client_id, action_id))
    except actions.ActionNotFound:
        raise HTTPException(404, "Proposal not found") from None


@router.post("/{action_id}/confirm", response_model=ActionView)
async def confirm(
    action_id: str, db: Db, client_id: ClientId, odoo: Annotated[OdooClient, Depends(get_odoo_client)]
) -> ActionView:
    try:
        return actions.to_view(await actions.confirm(db, client_id, action_id, odoo))
    except actions.ActionNotFound:
        raise HTTPException(404, "Proposal not found") from None
    except actions.ActionConflict as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/{action_id}/reject", response_model=ActionView)
async def reject(action_id: str, db: Db, client_id: ClientId) -> ActionView:
    try:
        return actions.to_view(await actions.reject(db, client_id, action_id))
    except actions.ActionNotFound:
        raise HTTPException(404, "Proposal not found") from None
    except actions.ActionConflict as exc:
        raise HTTPException(409, str(exc)) from None
