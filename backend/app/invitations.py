"""Household membership API for signed-in accounts."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .application.errors import RepositoryError
from .auth import SupabaseTokenVerifier
from .config import get_settings
from .infrastructure.repositories import SupabaseRepository


router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class InviteRequest(BaseModel):
    email: str


async def invitation_repository(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> SupabaseRepository:
    settings = get_settings()
    if not settings.supabase_configured:
        raise HTTPException(status_code=503, detail="Household invitations require Supabase")
    if not credentials or not await SupabaseTokenVerifier(settings).verify_token(credentials.credentials):
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return SupabaseRepository(settings, credentials.credentials)


Repository = Annotated[SupabaseRepository, Depends(invitation_repository)]


def _expected_error(exc: RepositoryError) -> HTTPException:
    message = str(exc)
    if message.startswith(("Only a household owner", "Sign in with")):
        code = 403
    elif message.startswith(("This invitation", "Pending invitation", "Collaborator", "This person", "This account")):
        code = 409
    elif message.startswith(("Enter a valid email", "Ask this person to sign up")):
        code = 422
    else:
        raise exc
    return HTTPException(status_code=code, detail=message)


async def _rpc(repository: SupabaseRepository, name: str, payload: dict[str, Any] | None = None) -> Any:
    try:
        return await repository.rpc(name, payload)
    except RepositoryError as exc:
        raise _expected_error(exc) from exc


@router.get("/api/household/access")
async def household_access(repository: Repository) -> dict:
    return await _rpc(repository, "household_access")


@router.post("/api/household/invitations")
async def create_invitation(payload: InviteRequest, repository: Repository) -> dict:
    return await _rpc(repository, "create_household_invitation", {"invitee_email": payload.email})


@router.delete("/api/household/invitations/{invitation_id}")
async def revoke_invitation(invitation_id: UUID, repository: Repository) -> dict:
    return await _rpc(repository, "revoke_household_invitation", {"invitation_id": str(invitation_id)})


@router.get("/api/invitations/mine")
async def my_invitations(repository: Repository) -> dict:
    return await _rpc(repository, "pending_household_invitations")


@router.post("/api/invitations/{invitation_id}/accept")
async def accept_invitation(invitation_id: UUID, repository: Repository) -> dict:
    return await _rpc(repository, "accept_household_invitation", {"invitation_id": str(invitation_id)})


@router.delete("/api/household/members/{member_id}")
async def remove_member(member_id: UUID, repository: Repository) -> dict:
    return await _rpc(repository, "remove_household_member", {"member_id": str(member_id)})
