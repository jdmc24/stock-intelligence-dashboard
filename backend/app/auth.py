from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.settings import settings

security = HTTPBearer(auto_error=False)


def require_bearer_token(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    if settings.api_bearer_token == "":
        return
    if creds is None or creds.scheme.lower() != "bearer" or creds.credentials != settings.api_bearer_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

