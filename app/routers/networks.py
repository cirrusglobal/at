"""Network provisioning and retrieval.

Every handler here is a plain `def`, not `async def`. boto3 is synchronous and
blocking; declaring these as sync lets FastAPI run them in its threadpool
instead of stalling the event loop for the duration of an AWS call.

Note the absence of any ownership or role check: the brief specifies that
authorization is open to all authenticated users, so `require_auth` is the
entire access policy.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.auth import require_auth
from app.deps import get_provisioner, get_repository
from app.errors import NetworkNotFound
from app.models import (
    NetworkCreateRequest,
    NetworkListResponse,
    NetworkResponse,
)
from app.services.repository import NetworkRepository
from app.services.vpc import VpcProvisioner

router = APIRouter()


@router.post(
    "",
    response_model=NetworkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a VPC with subnets",
)
def create_network(
    payload: NetworkCreateRequest,
    subject: str = Depends(require_auth),
    provisioner: VpcProvisioner = Depends(get_provisioner),
    repository: NetworkRepository = Depends(get_repository),
) -> NetworkResponse:
    # Provision first, persist second. A failed provision rolls itself back and
    # raises, so no record is written for resources that do not exist.
    record = provisioner.create(payload, created_by=subject)
    repository.put(record)
    return NetworkResponse(**record)


@router.get("", response_model=NetworkListResponse, summary="List networks")
def list_networks(
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = Query(None, description="Opaque cursor from a prior response"),
    subject: str = Depends(require_auth),
    repository: NetworkRepository = Depends(get_repository),
) -> NetworkListResponse:
    try:
        items, next_cursor = repository.list(limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return NetworkListResponse(
        items=[NetworkResponse(**item) for item in items],
        next_cursor=next_cursor,
    )


@router.get("/{network_id}", response_model=NetworkResponse, summary="Retrieve a network")
def get_network(
    network_id: str,
    subject: str = Depends(require_auth),
    repository: NetworkRepository = Depends(get_repository),
) -> NetworkResponse:
    record = repository.get(network_id)
    if record is None:
        raise NetworkNotFound(network_id)
    return NetworkResponse(**record)


@router.delete(
    "/{network_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a network and its AWS resources",
)
def delete_network(
    network_id: str,
    subject: str = Depends(require_auth),
    provisioner: VpcProvisioner = Depends(get_provisioner),
    repository: NetworkRepository = Depends(get_repository),
) -> Response:
    record = repository.get(network_id)
    if record is None:
        raise NetworkNotFound(network_id)

    # Cloud resources first, record second. If teardown fails the record
    # survives, so the caller can retry; dropping it first would strand the
    # resources with nothing pointing at them.
    provisioner.delete(record)
    repository.delete(network_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
