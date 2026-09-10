"""Request and response schemas.

All CIDR validation happens here, before the service layer makes a single AWS
call. Catching a malformed plan locally is both faster and far clearer than
surfacing a raw botocore error to the caller.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

# AWS accepts VPC and subnet CIDR blocks between /16 and /28 inclusive.
MIN_PREFIX_LEN = 16
MAX_PREFIX_LEN = 28


def _parse_cidr(value: str) -> ipaddress.IPv4Network:
    """Parse an IPv4 CIDR, rejecting host bits (strict) and IPv6."""
    try:
        network = ipaddress.IPv4Network(value, strict=True)
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"{value!r} is not a valid IPv4 address: {exc}") from exc
    except ipaddress.NetmaskValueError as exc:
        raise ValueError(f"{value!r} has an invalid netmask: {exc}") from exc
    except ValueError as exc:
        # strict=True raises plain ValueError when host bits are set.
        raise ValueError(
            f"{value!r} has host bits set; use the network address "
            f"(e.g. {ipaddress.IPv4Network(value, strict=False)})"
        ) from exc

    if not MIN_PREFIX_LEN <= network.prefixlen <= MAX_PREFIX_LEN:
        raise ValueError(
            f"{value!r} has a /{network.prefixlen} prefix; AWS requires "
            f"/{MIN_PREFIX_LEN} to /{MAX_PREFIX_LEN}"
        )
    return network


ResourceName = Annotated[str, Field(min_length=1, max_length=64)]


class NetworkStatus(StrEnum):
    AVAILABLE = "available"
    DELETING = "deleting"


class SubnetRequest(BaseModel):
    name: ResourceName
    cidr_block: str
    availability_zone: str = Field(min_length=1, max_length=32)
    public: bool = False

    @field_validator("cidr_block")
    @classmethod
    def _validate_cidr(cls, value: str) -> str:
        _parse_cidr(value)
        return value


class NetworkCreateRequest(BaseModel):
    name: ResourceName
    cidr_block: str
    subnets: list[SubnetRequest] = Field(min_length=1)

    @field_validator("cidr_block")
    @classmethod
    def _validate_cidr(cls, value: str) -> str:
        _parse_cidr(value)
        return value

    @model_validator(mode="after")
    def _validate_subnet_plan(self) -> NetworkCreateRequest:
        vpc_cidr = _parse_cidr(self.cidr_block)

        names = [s.name for s in self.subnets]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"duplicate subnet names: {sorted(duplicates)}")

        parsed = [(s, _parse_cidr(s.cidr_block)) for s in self.subnets]

        for subnet, cidr in parsed:
            if not cidr.subnet_of(vpc_cidr):
                raise ValueError(
                    f"subnet {subnet.name!r} ({cidr}) is not inside the VPC range {vpc_cidr}"
                )

        for i, (a, cidr_a) in enumerate(parsed):
            for b, cidr_b in parsed[i + 1 :]:
                if cidr_a.overlaps(cidr_b):
                    raise ValueError(
                        f"subnets {a.name!r} ({cidr_a}) and {b.name!r} ({cidr_b}) overlap"
                    )

        return self


class SubnetResponse(BaseModel):
    subnet_id: str
    name: str
    cidr_block: str
    availability_zone: str
    public: bool


class NetworkResponse(BaseModel):
    network_id: str
    name: str
    region: str
    cidr_block: str
    vpc_id: str
    status: NetworkStatus
    subnets: list[SubnetResponse]
    internet_gateway_id: str | None = None
    route_table_ids: list[str] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    updated_at: datetime


class NetworkListResponse(BaseModel):
    items: list[NetworkResponse]
    # Opaque; pass back as ?cursor= to fetch the next page.
    next_cursor: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)
