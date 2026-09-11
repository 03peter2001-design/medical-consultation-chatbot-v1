"""Response cache policy for clinical and authentication APIs."""

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response


async def prevent_api_response_caching(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Keep successful and failed API payloads out of browser/proxy caches."""

    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response
