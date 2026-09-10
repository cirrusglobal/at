"""EC2 orchestration: create a VPC with subnets, and tear it down again.

Two things here are worth more than the rest of the file:

1. **Ordering.** AWS networking resources have hard dependency ordering in both
   directions, and a couple of non-obvious quirks (see `_enable_dns_support`).
2. **Compensating rollback.** If subnet 3 of 4 fails, the first two subnets and
   the VPC already exist and will sit in the account indefinitely. Every
   resource id is tracked as it is created so a failure can unwind them in
   reverse order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError

from app.errors import ProvisioningError, RollbackIncomplete
from app.models import NetworkCreateRequest, NetworkStatus

logger = logging.getLogger(__name__)

DEFAULT_ROUTE = "0.0.0.0/0"

# Errors worth retrying are not handled here; botocore's standard retry mode
# already covers throttling and transient 5xx.
AWS_ERRORS = (ClientError, BotoCoreError)


@dataclass
class _Tracker:
    """Resources created so far, for rollback. Order matters on teardown."""

    vpc_id: str | None = None
    subnet_ids: list[str] = field(default_factory=list)
    internet_gateway_id: str | None = None
    internet_gateway_attached: bool = False
    route_table_ids: list[str] = field(default_factory=list)


class VpcProvisioner:
    def __init__(self, ec2_client: Any, region: str, managed_by_tag: str) -> None:
        self._ec2 = ec2_client
        self._region = region
        self._managed_by = managed_by_tag

    # ------------------------------------------------------------------ create

    def create(self, request: NetworkCreateRequest, created_by: str) -> dict:
        """Provision the VPC and return the record to persist.

        On any AWS failure, everything already created is deleted and a
        ProvisioningError is raised — or RollbackIncomplete if the cleanup
        itself failed, which is the only case where resources may be orphaned.
        """
        tracker = _Tracker()
        try:
            tracker.vpc_id = self._create_vpc(request)
            self._enable_dns_support(tracker.vpc_id)
            subnets = self._create_subnets(request, tracker)
            if any(s["public"] for s in subnets):
                self._create_public_routing(request, subnets, tracker)
        except AWS_ERRORS as exc:
            logger.warning("provisioning failed, rolling back: %s", exc)
            failures = self._teardown(tracker)
            if failures:
                raise RollbackIncomplete(
                    "Provisioning failed and cleanup did not fully succeed. "
                    "Resources may still exist and incur charges.",
                    details={"cleanup_errors": failures},
                ) from exc
            raise ProvisioningError(
                f"Failed to provision network: {exc}",
                details={"rolled_back": True},
            ) from exc

        now = datetime.now(UTC).isoformat()
        return {
            "network_id": str(uuid4()),
            "name": request.name,
            "region": self._region,
            "cidr_block": request.cidr_block,
            "vpc_id": tracker.vpc_id,
            "status": NetworkStatus.AVAILABLE.value,
            "subnets": subnets,
            "internet_gateway_id": tracker.internet_gateway_id,
            "route_table_ids": tracker.route_table_ids,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }

    def _create_vpc(self, request: NetworkCreateRequest) -> str:
        response = self._ec2.create_vpc(
            CidrBlock=request.cidr_block,
            TagSpecifications=[self._tag_spec("vpc", request.name)],
        )
        vpc_id = response["Vpc"]["VpcId"]
        # A VPC is not immediately usable for dependent calls.
        self._ec2.get_waiter("vpc_available").wait(VpcIds=[vpc_id])
        return vpc_id

    def _enable_dns_support(self, vpc_id: str) -> None:
        # These cannot be combined: EC2 rejects a ModifyVpcAttribute call that
        # carries both EnableDnsSupport and EnableDnsHostnames. Two calls, and
        # support must be enabled before hostnames.
        self._ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={"Value": True})
        self._ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})

    def _create_subnets(self, request: NetworkCreateRequest, tracker: _Tracker) -> list[dict]:
        subnets: list[dict] = []
        for spec in request.subnets:
            response = self._ec2.create_subnet(
                VpcId=tracker.vpc_id,
                CidrBlock=spec.cidr_block,
                AvailabilityZone=spec.availability_zone,
                TagSpecifications=[self._tag_spec("subnet", spec.name)],
            )
            subnet_id = response["Subnet"]["SubnetId"]
            tracker.subnet_ids.append(subnet_id)

            if spec.public:
                self._ec2.modify_subnet_attribute(
                    SubnetId=subnet_id, MapPublicIpOnLaunch={"Value": True}
                )

            subnets.append(
                {
                    "subnet_id": subnet_id,
                    "name": spec.name,
                    "cidr_block": spec.cidr_block,
                    "availability_zone": spec.availability_zone,
                    "public": spec.public,
                }
            )
        return subnets

    def _create_public_routing(
        self, request: NetworkCreateRequest, subnets: list[dict], tracker: _Tracker
    ) -> None:
        """Internet gateway + a shared public route table, only if needed.

        Private subnets deliberately get no NAT gateway: ~$32/month each and
        minutes to provision. See README for the reasoning.
        """
        igw = self._ec2.create_internet_gateway(
            TagSpecifications=[self._tag_spec("internet-gateway", f"{request.name}-igw")]
        )
        igw_id = igw["InternetGateway"]["InternetGatewayId"]
        tracker.internet_gateway_id = igw_id

        self._ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=tracker.vpc_id)
        tracker.internet_gateway_attached = True

        route_table = self._ec2.create_route_table(
            VpcId=tracker.vpc_id,
            TagSpecifications=[self._tag_spec("route-table", f"{request.name}-public")],
        )
        route_table_id = route_table["RouteTable"]["RouteTableId"]
        tracker.route_table_ids.append(route_table_id)

        self._ec2.create_route(
            RouteTableId=route_table_id,
            DestinationCidrBlock=DEFAULT_ROUTE,
            GatewayId=igw_id,
        )

        for subnet in subnets:
            if subnet["public"]:
                self._ec2.associate_route_table(
                    RouteTableId=route_table_id, SubnetId=subnet["subnet_id"]
                )

    # ------------------------------------------------------------------ delete

    def delete(self, record: dict) -> None:
        """Tear down a previously provisioned network."""
        tracker = _Tracker(
            vpc_id=record.get("vpc_id"),
            subnet_ids=[s["subnet_id"] for s in record.get("subnets", [])],
            internet_gateway_id=record.get("internet_gateway_id"),
            internet_gateway_attached=bool(record.get("internet_gateway_id")),
            route_table_ids=list(record.get("route_table_ids", [])),
        )
        failures = self._teardown(tracker)
        if failures:
            raise ProvisioningError("Failed to fully delete network", details={"errors": failures})

    def _teardown(self, tracker: _Tracker) -> list[str]:
        """Delete in reverse dependency order. Best effort: collect, don't stop.

        Returns a list of human-readable failures; empty means fully cleaned up.
        """
        failures: list[str] = []

        # Route tables must be disassociated before they can be deleted, and
        # the VPC's main route table must never be touched.
        for route_table_id in tracker.route_table_ids:
            try:
                described = self._ec2.describe_route_tables(RouteTableIds=[route_table_id])
                for association in described["RouteTables"][0].get("Associations", []):
                    if association.get("Main"):
                        continue
                    self._ec2.disassociate_route_table(
                        AssociationId=association["RouteTableAssociationId"]
                    )
                self._ec2.delete_route_table(RouteTableId=route_table_id)
            except AWS_ERRORS as exc:
                failures.append(f"route table {route_table_id}: {exc}")

        if tracker.internet_gateway_id:
            if tracker.internet_gateway_attached and tracker.vpc_id:
                try:
                    self._ec2.detach_internet_gateway(
                        InternetGatewayId=tracker.internet_gateway_id,
                        VpcId=tracker.vpc_id,
                    )
                except AWS_ERRORS as exc:
                    failures.append(f"detach igw {tracker.internet_gateway_id}: {exc}")
            try:
                self._ec2.delete_internet_gateway(InternetGatewayId=tracker.internet_gateway_id)
            except AWS_ERRORS as exc:
                failures.append(f"igw {tracker.internet_gateway_id}: {exc}")

        for subnet_id in tracker.subnet_ids:
            try:
                self._ec2.delete_subnet(SubnetId=subnet_id)
            except AWS_ERRORS as exc:
                failures.append(f"subnet {subnet_id}: {exc}")

        if tracker.vpc_id:
            try:
                self._ec2.delete_vpc(VpcId=tracker.vpc_id)
            except AWS_ERRORS as exc:
                failures.append(f"vpc {tracker.vpc_id}: {exc}")

        return failures

    # ------------------------------------------------------------------ helper

    def _tag_spec(self, resource_type: str, name: str) -> dict:
        """Tag at creation time rather than with a follow-up CreateTags call.

        One fewer call, and no window where a resource exists untagged — which
        matters because ManagedBy is how orphans get found later.
        """
        return {
            "ResourceType": resource_type,
            "Tags": [
                {"Key": "Name", "Value": name},
                {"Key": "ManagedBy", "Value": self._managed_by},
            ],
        }
