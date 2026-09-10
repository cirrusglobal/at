"""Token issuance."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.auth import authenticate_user, create_access_token
from app.config import Settings, get_settings
from app.models import TokenResponse

router = APIRouter()


@router.post("/token", response_model=TokenResponse, summary="Obtain an access token")
def issue_token(
    form: OAuth2PasswordRequestForm = Depends(),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Standard OAuth2 password flow, so Swagger UI's Authorize button works."""
    if not authenticate_user(form.username, form.password, settings):
        # One message for both failure modes: never reveal which half was wrong.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in = create_access_token(form.username, settings)
    return TokenResponse(access_token=token, expires_in=expires_in)
