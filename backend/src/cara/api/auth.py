"""Logging in, and who may do what: tokens, the current user, superusers, and roles in a study."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Path, status
from fastapi.security import OAuth2PasswordBearer

from cara.api.deps import AppSettingsDep, UsersDep
from cara.config import AppSettings
from cara.db.models import Role, UserRow
from cara.errors import NotFound

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def create_token(username: str, settings: AppSettings) -> str:
    """Return a signed login token for the user, valid for `settings.token_minutes`."""
    expires = datetime.now(UTC) + timedelta(minutes=settings.token_minutes)
    return jwt.encode({"sub": username, "exp": expires}, settings.secret_key, algorithm="HS256")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], users: UsersDep, settings: AppSettingsDep
) -> UserRow:
    """Return the account the request's token belongs to.

    Raises:
        HTTPException: 401 when the token is invalid, expired, or names an account that no longer exists.
    """
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
    )
    try:
        username = jwt.decode(token, settings.secret_key, algorithms=["HS256"])["sub"]
        return users.get(username)
    except (jwt.InvalidTokenError, NotFound) as error:
        raise unauthorized from error


CurrentUserDep = Annotated[UserRow, Depends(get_current_user)]


def require_superuser(user: CurrentUserDep) -> UserRow:
    """Let only superusers through (HTTP 403 for anyone else)."""
    if not user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "superusers only")
    return user


SuperuserDep = Annotated[UserRow, Depends(require_superuser)]


def get_study_role(study_id: Annotated[int, Path()], user: CurrentUserDep, users: UsersDep) -> Role:
    """Return the person's role in the study in the path (404 if it doesn't exist, 403 for non-members)."""
    return users.role_in(user, study_id)


def require_admin(role: Annotated[Role, Depends(get_study_role)]) -> Role:
    """Let only the study's admins through (HTTP 403 for annotators)."""
    if role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "study admins only")
    return role


def require_annotator(role: Annotated[Role, Depends(get_study_role)]) -> Role:
    """Let only the study's annotators through (HTTP 403 for admins).

    Admins manage and annotators judge: someone who does both uses two accounts.
    """
    if role != Role.ANNOTATOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "annotators only: admins manage, annotators judge")
    return role


StudyRoleDep = Annotated[Role, Depends(get_study_role)]
StudyAdminDep = Annotated[Role, Depends(require_admin)]
StudyAnnotatorDep = Annotated[Role, Depends(require_annotator)]
