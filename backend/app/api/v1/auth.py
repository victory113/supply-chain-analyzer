"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.auth import Token, UserLogin, UserRead, UserRegister
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and receive a token",
)
async def register(payload: UserRegister, session: DbSession) -> Token:
    service = AuthService(session)
    user = await service.register(payload)
    # Log the user straight in — an extra round trip here buys nothing.
    return service.issue_token(user)


@router.post("/login", response_model=Token, summary="Exchange credentials for a token")
async def login(payload: UserLogin, session: DbSession) -> Token:
    service = AuthService(session)
    user = await service.authenticate(payload.email, payload.password)
    return service.issue_token(user)


@router.get("/me", response_model=UserRead, summary="Current user profile")
async def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)
