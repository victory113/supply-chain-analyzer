"""Registration, login, and token issuance."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError, ForbiddenError
from app.core.logging import get_logger
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import Token, UserRead, UserRegister

logger = get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def register(self, payload: UserRegister) -> User:
        email = payload.email.strip().lower()
        if await self.users.email_exists(email):
            raise ConflictError("An account with that email already exists.")

        user = User(
            email=email,
            password_hash=hash_password(payload.password),
            full_name=payload.full_name,
            organization=payload.organization,
        )
        await self.users.add(user)
        await self.session.commit()
        logger.info("user_registered", user_id=str(user.id))
        return user

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.users.get_by_email(email)

        # Hash a dummy password when the user is missing so the response time
        # doesn't reveal whether an address is registered.
        if user is None:
            verify_password(password, hash_password("timing-equalizer"))
            raise AuthenticationError("Incorrect email or password.")

        if not verify_password(password, user.password_hash):
            logger.info("login_failed", email=email)
            raise AuthenticationError("Incorrect email or password.")

        if not user.is_active:
            raise ForbiddenError("This account is disabled.")

        return user

    def issue_token(self, user: User) -> Token:
        ttl_seconds = settings.access_token_ttl_minutes * 60
        token = create_access_token(str(user.id), email=user.email)
        return Token(
            access_token=token,
            expires_in=ttl_seconds,
            user=UserRead.model_validate(user),
        )

    async def get_active_user(self, user_id: uuid.UUID) -> User:
        user = await self.users.get(user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("User no longer exists or is inactive.")
        return user
