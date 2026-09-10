"""Provisioning internals — chiefly that failures don't strand resources.

A half-built VPC is the expensive failure mode: it bills, it consumes address
space, and nothing in the API points at it. These tests inject failures at each
stage and assert the account is left clean.
"""

import pytest
from botocore.exceptions import ClientError

from app.errors import ProvisioningError, RollbackIncomplete
from app.models import NetworkCreateRequest
from tests.conftest import REGION, managed_subnets, managed_vpcs


def _client_error(operation: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": "InvalidParameterValue", "Message": "injected failure"}},
        operation,
    )


@pytest.fixture
def three_subnet_request(payload) -> NetworkCreateRequest:
    payload["subnets"] = [
        {
            "name": f"tier-{i}",
            "cidr_block": f"10.0.{i}.0/24",
            "availability_zone": f"{REGION}{letter}",
            "public": i == 1,
        }
        for i, letter in enumerate("abc", start=1)
    ]
    return NetworkCreateRequest(**payload)


def test_failure_midway_through_subnets_rolls_back(
    provisioner, ec2_client, three_subnet_request, monkeypatch
):
    """Fail on subnet 2 of 3: subnet 1 and the VPC must both be removed."""
    original = ec2_client.create_subnet
    calls = {"count": 0}

    def flaky_create_subnet(**kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise _client_error("CreateSubnet")
        return original(**kwargs)

    monkeypatch.setattr(ec2_client, "create_subnet", flaky_create_subnet)

    with pytest.raises(ProvisioningError) as excinfo:
        provisioner.create(three_subnet_request, created_by="demo")

    assert excinfo.value.details["rolled_back"] is True
    assert managed_vpcs(ec2_client) == []
    assert managed_subnets(ec2_client) == []


def test_failure_after_gateway_attached_rolls_back_gateway(
    provisioner, ec2_client, payload, monkeypatch
):
    """Fail during routing, once the IGW is already attached to the VPC."""

    def failing_create_route(**kwargs):
        raise _client_error("CreateRoute")

    monkeypatch.setattr(ec2_client, "create_route", failing_create_route)

    with pytest.raises(ProvisioningError):
        provisioner.create(NetworkCreateRequest(**payload), created_by="demo")

    assert managed_vpcs(ec2_client) == []
    assert managed_subnets(ec2_client) == []
    # An attached gateway has to be detached before deletion; if that ordering
    # were wrong, the gateway would survive here.
    assert ec2_client.describe_internet_gateways()["InternetGateways"] == []


def test_failed_cleanup_reports_distinctly(provisioner, ec2_client, payload, monkeypatch):
    """Provisioning fails AND cleanup fails — the caller must be told resources
    may still exist, rather than getting a plain 'rolled back' error."""

    def failing_create_subnet(**kwargs):
        raise _client_error("CreateSubnet")

    def failing_delete_vpc(**kwargs):
        raise _client_error("DeleteVpc")

    monkeypatch.setattr(ec2_client, "create_subnet", failing_create_subnet)
    monkeypatch.setattr(ec2_client, "delete_vpc", failing_delete_vpc)

    with pytest.raises(RollbackIncomplete) as excinfo:
        provisioner.create(NetworkCreateRequest(**payload), created_by="demo")

    assert excinfo.value.details["cleanup_errors"]
    assert excinfo.value.status_code == 500


def test_dns_attributes_require_two_separate_calls(provisioner, ec2_client, payload, monkeypatch):
    """EC2 rejects ModifyVpcAttribute carrying both flags at once, and support
    must precede hostnames. Pinned here so a future 'tidy-up' cannot merge them."""
    original = ec2_client.modify_vpc_attribute
    observed: list[set[str]] = []

    def spy(**kwargs):
        observed.append(set(kwargs) - {"VpcId"})
        return original(**kwargs)

    monkeypatch.setattr(ec2_client, "modify_vpc_attribute", spy)
    provisioner.create(NetworkCreateRequest(**payload), created_by="demo")

    assert observed == [{"EnableDnsSupport"}, {"EnableDnsHostnames"}]


def test_resources_tagged_for_later_discovery(provisioner, ec2_client, payload):
    record = provisioner.create(NetworkCreateRequest(**payload), created_by="demo")

    vpc = ec2_client.describe_vpcs(VpcIds=[record["vpc_id"]])["Vpcs"][0]
    tags = {t["Key"]: t["Value"] for t in vpc["Tags"]}
    assert tags["ManagedBy"] == "vpc-provisioning-api"
    assert tags["Name"] == "demo-network"


def test_public_subnet_maps_public_ip_on_launch(provisioner, ec2_client, payload):
    record = provisioner.create(NetworkCreateRequest(**payload), created_by="demo")

    by_id = {s["subnet_id"]: s for s in record["subnets"]}
    described = ec2_client.describe_subnets(SubnetIds=list(by_id))["Subnets"]

    for subnet in described:
        expected = by_id[subnet["SubnetId"]]["public"]
        assert subnet["MapPublicIpOnLaunch"] is expected


def test_api_persists_nothing_when_provisioning_fails(
    client, auth, payload, ec2_client, monkeypatch
):
    def failing_create_subnet(**kwargs):
        raise _client_error("CreateSubnet")

    monkeypatch.setattr(ec2_client, "create_subnet", failing_create_subnet)

    response = client.post("/v1/networks", json=payload, headers=auth)
    assert response.status_code == 502
    assert response.json()["code"] == "provisioning_failed"

    # No orphaned record for resources that no longer exist.
    assert client.get("/v1/networks", headers=auth).json()["items"] == []
