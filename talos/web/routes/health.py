"""GET /api/health."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Depends

from talos.web.deps import Services, get_services
from talos.web.schemas import HealthOut

router = APIRouter()


def app_version() -> str:
    """The installed talos-ai package version.

    Returns:
        The version string, or "0.0.0" when the package isn't installed.
    """
    try:
        return version("talos-ai")
    except PackageNotFoundError:
        return "0.0.0"


@router.get("/health", response_model=HealthOut)
async def health(services: Services = Depends(get_services)) -> HealthOut:
    """Liveness plus whether the database answers and which graph is running."""
    return HealthOut(
        ok=True,
        db=await services.store.ping(),
        fake_graph=services.fake_graph,
        version=app_version(),
    )
