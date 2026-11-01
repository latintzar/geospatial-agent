"""Local-first API boundary for recipient-owned geospatial providers."""

from dataclasses import dataclass, field
import hmac, ipaddress, os
from urllib.parse import urlsplit
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

MAX_BODY = 16384


@dataclass(frozen=True)
class Policy:
    origins: tuple[str, ...]
    public: bool = False
    token: str = field(default="", repr=False)

    @classmethod
    def from_env(cls):
        origins = tuple(
            x.strip()
            for x in os.getenv(
                "GEOSPATIAL_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
            ).split(",")
            if x.strip()
        )
        for origin in origins:
            u = urlsplit(origin)
            if (
                u.scheme not in {"http", "https"}
                or not u.hostname
                or u.username
                or u.password
                or u.path
                or u.query
                or u.fragment
                or "*" in origin
            ):
                raise ValueError("Configure exact frontend origins in GEOSPATIAL_ALLOWED_ORIGINS.")
        value = os.getenv("GEOSPATIAL_PUBLIC_API", "false")
        if value not in {"true", "false"}:
            raise ValueError("GEOSPATIAL_PUBLIC_API must be true or false.")
        token = os.getenv("GEOSPATIAL_API_TOKEN", "")
        if value == "true" and len(token) < 32:
            raise ValueError(
                "A public API requires a private GEOSPATIAL_API_TOKEN of at least 32 characters."
            )
        return cls(origins, value == "true", token)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=4096)
    # Retained browser contract; the commissioned server selects its actual model.
    model: str = Field(default="gemini-3-flash-preview", min_length=1, max_length=80)


class DiemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    top_k: int = Field(default=1000, ge=1, le=1000)


def denial(policy, host, headers):
    origin = headers.get("origin")
    if origin and origin not in policy.origins:
        return 403, "Use the configured frontend origin."
    try:
        local = ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        local = False
    if not policy.public and not local:
        return 403, "This API accepts local requests."
    if policy.token and not hmac.compare_digest(
        headers.get("authorization", ""), "Bearer " + policy.token
    ):
        return 401, "Provide the configured API authorization."
    return None


def mount_boundary(app, policy):
    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.url.path not in {"/stream-chat", "/stream-diem"} or request.method == "OPTIONS":
            return await call_next(request)
        error = denial(policy, request.client.host if request.client else "", request.headers)
        if error:
            return JSONResponse({"detail": error[1]}, status_code=error[0])
        if request.method == "POST":
            try:
                declared = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Send a valid request length."}, status_code=400)
            if not 0 <= declared <= MAX_BODY:
                return JSONResponse({"detail": "Use a smaller request."}, status_code=413)
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_BODY:
                    return JSONResponse({"detail": "Use a smaller request."}, status_code=413)
                body.extend(chunk)
            # Starlette's cached request replays this bounded body to FastAPI.
            request._body = bytes(body)
        return await call_next(request)
