from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import Principal, get_current_principal, get_roles_repo, get_users_repo
from app.core.config import Settings, get_settings
from app.core.permissions import effective_permissions
from app.core.security import create_access_token, hash_password, verify_password
from app.repositories.roles import RolesRepository
from app.repositories.users import UsersRepository
from app.schemas.auth import ChangePasswordRequest, LoginRequest, TokenResponse
from app.schemas.user import CurrentUser, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _current_user(user: dict, permissions: set[str]) -> CurrentUser:
    return CurrentUser(**UserOut.from_doc(user).model_dump(), permissions=sorted(permissions))


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    users: UsersRepository = Depends(get_users_repo),
    roles: RolesRepository = Depends(get_roles_repo),
) -> TokenResponse:
    user = await users.find_by_email(payload.email)
    password_ok = await run_in_threadpool(
        verify_password, payload.password, user["password_hash"] if user else None
    )
    if not user or not password_ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.get("is_active", True):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    await users.touch_last_login(user["_id"])
    token = create_access_token(str(user["_id"]), settings)
    max_age = settings.jwt_expire_minutes * 60
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    permissions = effective_permissions(await roles.get(user["role"]))
    return TokenResponse(access_token=token, expires_in=max_age, user=_current_user(user, permissions))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: Settings = Depends(get_settings)) -> None:
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


@router.get("/me", response_model=CurrentUser)
async def me(principal: Principal = Depends(get_current_principal)) -> CurrentUser:
    return _current_user(principal.user, principal.permissions)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    principal: Principal = Depends(get_current_principal),
    users: UsersRepository = Depends(get_users_repo),
) -> None:
    user = principal.user
    if not await run_in_threadpool(verify_password, payload.current_password, user["password_hash"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="New password must differ from the current one")

    new_hash = await run_in_threadpool(hash_password, payload.new_password)
    await users.update(str(user["_id"]), {"password_hash": new_hash})
