from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import ReadinessService

router = APIRouter(tags=["health"])
SERVICE_NAME = "tender-phase1"


def get_readiness_service(db: Session = Depends(get_db)) -> ReadinessService:
    return ReadinessService(session=db, service_name=SERVICE_NAME)


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@router.get("/readyz")
def readyz(
    response: Response,
    service: ReadinessService = Depends(get_readiness_service),
) -> dict[str, object]:
    report = service.build_report()
    if not report.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report.to_payload()
