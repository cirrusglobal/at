"""Shared fixtures. The whole suite runs against moto — no AWS account, no network."""

from __future__ import annotations

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.config import Settings, get_settings
from app.deps import get_ec2_client, get_provisioner, get_repository
from app.main import create_app
from app.services.repository import NetworkRepository, build_table
from app.services.vpc import VpcProvisioner

REGION = "eu-central-1"
TABLE_NAME = "networks-test"
MANAGED_BY = "vpc-provisioning-api"


@pytest.fixture(autouse=True)
def _fake_aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee no test can reach real AWS, even if moto were misconfigured."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.delenv("AWS_PROFILE", raising=False)


@pytest.fixture
def aws():
    with mock_aws():
        yield


@pytest.fixture
def settings() -> Settings:
    return Settings(
        aws_region=REGION,
        dynamodb_table_name=TABLE_NAME,
        dynamodb_endpoint_url=None,
        # >= 32 bytes, matching the HS256 recommendation in RFC 7518 §3.2
        jwt_secret="test-secret-that-is-long-enough-for-hs256",
        access_token_ttl_minutes=60,
        demo_username="demo",
        demo_password="demo-password",
        managed_by_tag=MANAGED_BY,
    )


@pytest.fixture
def ec2_client(aws):
    return boto3.client("ec2", region_name=REGION)


@pytest.fixture
def repository(aws) -> NetworkRepository:
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return NetworkRepository(build_table(dynamodb, TABLE_NAME))


@pytest.fixture
def provisioner(ec2_client, settings) -> VpcProvisioner:
    return VpcProvisioner(ec2_client, REGION, settings.managed_by_tag)


@pytest.fixture
def client(settings, ec2_client, repository, provisioner) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ec2_client] = lambda: ec2_client
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_provisioner] = lambda: provisioner
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth(client, settings) -> dict[str, str]:
    response = client.post(
        "/v1/auth/token",
        data={"username": settings.demo_username, "password": settings.demo_password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def payload() -> dict:
    """One public and one private subnet, in different AZs."""
    return {
        "name": "demo-network",
        "cidr_block": "10.0.0.0/16",
        "subnets": [
            {
                "name": "public-a",
                "cidr_block": "10.0.1.0/24",
                "availability_zone": f"{REGION}a",
                "public": True,
            },
            {
                "name": "private-b",
                "cidr_block": "10.0.2.0/24",
                "availability_zone": f"{REGION}b",
                "public": False,
            },
        ],
    }


def managed_vpcs(ec2_client) -> list[dict]:
    """VPCs this service created — excludes the account's default VPC."""
    return ec2_client.describe_vpcs(Filters=[{"Name": "tag:ManagedBy", "Values": [MANAGED_BY]}])[
        "Vpcs"
    ]


def managed_subnets(ec2_client) -> list[dict]:
    return ec2_client.describe_subnets(Filters=[{"Name": "tag:ManagedBy", "Values": [MANAGED_BY]}])[
        "Subnets"
    ]
