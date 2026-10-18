"""Logging in."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from cara.api.auth import CurrentUserDep, create_token
from cara.api.deps import AppSettingsDep, UsersDep
from cara.api.schemas import Token, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token")
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], users: UsersDep, settings: AppSettingsDep
) -> Token:
    """Exchange a username and password for a login token."""
    user = users.authenticate(form.username, form.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    return Token(access_token=create_token(user.username, settings))


@router.get("/me")
def me(user: CurrentUserDep) -> UserOut:
    """Return who is logged in."""
    return UserOut(username=user.username, is_superuser=user.is_superuser)
