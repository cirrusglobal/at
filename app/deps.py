"""FastAPI dependency providers for AWS clients and the repository.

Clients are cached rather than rebuilt per request — constructing a boto3
client parses service JSON and is far too expensive to do on a hot path.
Tests bypass all of this with `app.dependency_overrides`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3
from fastapi import Depends

from app.config import Settings, get_settings
from app.services.repository import NetworkRepository, build_table
from app.services.vpc import VpcProvisioner


@lru_cache
def _build_ec2_client(region: str) -> Any:
    return boto3.client("ec2", region_name=region)


@lru_cache
def _build_repository(
    region: str, table_name: str, endpoint_url: str | None, auto_create: bool
) -> NetworkRepository:
    dynamodb = boto3.resource("dynamodb", region_name=region, endpoint_url=endpoint_url)
    return NetworkRepository(build_table(dynamodb, table_name, create_if_missing=auto_create))


def get_ec2_client(settings: Settings = Depends(get_settings)) -> Any:
    return _build_ec2_client(settings.aws_region)


def get_repository(settings: Settings = Depends(get_settings)) -> NetworkRepository:
    return _build_repository(
        settings.aws_region,
        settings.dynamodb_table_name,
        settings.dynamodb_endpoint_url,
        settings.auto_create_table,
    )


def get_provisioner(
    ec2_client: Any = Depends(get_ec2_client),
    settings: Settings = Depends(get_settings),
) -> VpcProvisioner:
    return VpcProvisioner(ec2_client, settings.aws_region, settings.managed_by_tag)
