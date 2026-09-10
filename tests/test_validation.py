"""CIDR plan validation — rejected before any AWS call is made."""

import pytest
from pydantic import ValidationError

from app.models import NetworkCreateRequest


def _request(**overrides) -> dict:
    base = {
        "name": "net",
        "cidr_block": "10.0.0.0/16",
        "subnets": [
            {
                "name": "a",
                "cidr_block": "10.0.1.0/24",
                "availability_zone": "eu-central-1a",
                "public": False,
            }
        ],
    }
    return {**base, **overrides}


def test_valid_plan_accepted():
    request = NetworkCreateRequest(**_request())
    assert request.cidr_block == "10.0.0.0/16"
    assert len(request.subnets) == 1


def test_subnet_outside_vpc_range_rejected():
    payload = _request(
        subnets=[
            {
                "name": "a",
                "cidr_block": "192.168.1.0/24",
                "availability_zone": "eu-central-1a",
            }
        ]
    )
    with pytest.raises(ValidationError, match="not inside the VPC range"):
        NetworkCreateRequest(**payload)


def test_overlapping_subnets_rejected():
    payload = _request(
        subnets=[
            {"name": "a", "cidr_block": "10.0.0.0/23", "availability_zone": "eu-central-1a"},
            {"name": "b", "cidr_block": "10.0.1.0/24", "availability_zone": "eu-central-1b"},
        ]
    )
    with pytest.raises(ValidationError, match="overlap"):
        NetworkCreateRequest(**payload)


def test_adjacent_subnets_allowed():
    """Adjacent is not overlapping — this must not be a false positive."""
    payload = _request(
        subnets=[
            {"name": "a", "cidr_block": "10.0.0.0/24", "availability_zone": "eu-central-1a"},
            {"name": "b", "cidr_block": "10.0.1.0/24", "availability_zone": "eu-central-1b"},
        ]
    )
    assert len(NetworkCreateRequest(**payload).subnets) == 2


@pytest.mark.parametrize("cidr", ["10.0.0.0/8", "10.0.0.0/15", "10.0.0.0/29", "10.0.0.0/32"])
def test_vpc_prefix_outside_aws_limits_rejected(cidr):
    with pytest.raises(ValidationError, match="AWS requires"):
        NetworkCreateRequest(**_request(cidr_block=cidr))


def test_host_bits_set_rejected():
    with pytest.raises(ValidationError, match="host bits set"):
        NetworkCreateRequest(**_request(cidr_block="10.0.0.5/16"))


def test_malformed_cidr_rejected():
    with pytest.raises(ValidationError):
        NetworkCreateRequest(**_request(cidr_block="not-a-cidr"))


def test_duplicate_subnet_names_rejected():
    payload = _request(
        subnets=[
            {"name": "dup", "cidr_block": "10.0.1.0/24", "availability_zone": "eu-central-1a"},
            {"name": "dup", "cidr_block": "10.0.2.0/24", "availability_zone": "eu-central-1b"},
        ]
    )
    with pytest.raises(ValidationError, match="duplicate subnet names"):
        NetworkCreateRequest(**payload)


def test_at_least_one_subnet_required():
    with pytest.raises(ValidationError):
        NetworkCreateRequest(**_request(subnets=[]))


def test_api_returns_422_for_invalid_plan(client, auth, payload):
    payload["subnets"][0]["cidr_block"] = "172.16.0.0/24"  # outside 10.0.0.0/16
    response = client.post("/v1/networks", json=payload, headers=auth)
    assert response.status_code == 422
    assert "not inside the VPC range" in response.text


def test_validation_runs_before_any_aws_call(client, auth, payload, ec2_client):
    """A rejected plan must not leave a half-built VPC behind."""
    from tests.conftest import managed_vpcs

    payload["cidr_block"] = "10.0.0.0/8"
    assert client.post("/v1/networks", json=payload, headers=auth).status_code == 422
    assert managed_vpcs(ec2_client) == []
