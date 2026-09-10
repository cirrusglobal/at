"""End-to-end API behaviour: create, retrieve, list, delete."""

from tests.conftest import REGION, managed_subnets, managed_vpcs


def test_create_returns_created_resources(client, auth, payload, ec2_client):
    response = client.post("/v1/networks", json=payload, headers=auth)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["vpc_id"].startswith("vpc-")
    assert body["status"] == "available"
    assert body["region"] == REGION
    assert body["created_by"] == "demo"
    assert len(body["subnets"]) == 2
    assert all(s["subnet_id"].startswith("subnet-") for s in body["subnets"])

    # The resources actually exist in AWS, not just in the response body.
    vpcs = managed_vpcs(ec2_client)
    assert len(vpcs) == 1
    assert vpcs[0]["CidrBlock"] == "10.0.0.0/16"
    assert len(managed_subnets(ec2_client)) == 2


def test_created_network_is_persisted_and_retrievable(client, auth, payload):
    created = client.post("/v1/networks", json=payload, headers=auth).json()

    fetched = client.get(f"/v1/networks/{created['network_id']}", headers=auth)
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_dns_attributes_enabled(client, auth, payload, ec2_client):
    body = client.post("/v1/networks", json=payload, headers=auth).json()
    vpc_id = body["vpc_id"]

    support = ec2_client.describe_vpc_attribute(VpcId=vpc_id, Attribute="enableDnsSupport")
    hostnames = ec2_client.describe_vpc_attribute(VpcId=vpc_id, Attribute="enableDnsHostnames")
    assert support["EnableDnsSupport"]["Value"] is True
    assert hostnames["EnableDnsHostnames"]["Value"] is True


def test_public_subnet_gets_gateway_and_route(client, auth, payload, ec2_client):
    body = client.post("/v1/networks", json=payload, headers=auth).json()

    assert body["internet_gateway_id"].startswith("igw-")
    assert len(body["route_table_ids"]) == 1

    route_table = ec2_client.describe_route_tables(RouteTableIds=body["route_table_ids"])[
        "RouteTables"
    ][0]

    default_routes = [
        r for r in route_table["Routes"] if r.get("DestinationCidrBlock") == "0.0.0.0/0"
    ]
    assert len(default_routes) == 1
    assert default_routes[0]["GatewayId"] == body["internet_gateway_id"]

    # Only the public subnet is associated.
    associated = {a["SubnetId"] for a in route_table.get("Associations", []) if a.get("SubnetId")}
    public_id = next(s["subnet_id"] for s in body["subnets"] if s["public"])
    assert associated == {public_id}


def test_private_only_network_creates_no_gateway(client, auth, payload, ec2_client):
    for subnet in payload["subnets"]:
        subnet["public"] = False

    body = client.post("/v1/networks", json=payload, headers=auth).json()

    assert body["internet_gateway_id"] is None
    assert body["route_table_ids"] == []
    assert ec2_client.describe_internet_gateways()["InternetGateways"] == []


def test_list_returns_newest_first(client, auth, payload):
    names = ["first", "second", "third"]
    for index, name in enumerate(names):
        payload["name"] = name
        payload["cidr_block"] = f"10.{index}.0.0/16"
        payload["subnets"] = [
            {
                "name": f"{name}-a",
                "cidr_block": f"10.{index}.1.0/24",
                "availability_zone": f"{REGION}a",
                "public": False,
            }
        ]
        assert client.post("/v1/networks", json=payload, headers=auth).status_code == 201

    listed = client.get("/v1/networks", headers=auth).json()
    assert [item["name"] for item in listed["items"]] == list(reversed(names))
    assert listed["next_cursor"] is None


def test_list_paginates(client, auth, payload):
    for index in range(3):
        payload["name"] = f"net-{index}"
        payload["cidr_block"] = f"10.{index}.0.0/16"
        payload["subnets"] = [
            {
                "name": "a",
                "cidr_block": f"10.{index}.1.0/24",
                "availability_zone": f"{REGION}a",
                "public": False,
            }
        ]
        client.post("/v1/networks", json=payload, headers=auth)

    first = client.get("/v1/networks?limit=2", headers=auth).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"]

    second = client.get(f"/v1/networks?limit=2&cursor={first['next_cursor']}", headers=auth).json()
    assert len(second["items"]) == 1

    ids = {i["network_id"] for i in first["items"]} | {i["network_id"] for i in second["items"]}
    assert len(ids) == 3


def test_malformed_cursor_returns_400(client, auth):
    response = client.get("/v1/networks?cursor=%%%not-base64%%%", headers=auth)
    assert response.status_code == 400


def test_unknown_network_returns_404(client, auth):
    response = client.get("/v1/networks/does-not-exist", headers=auth)
    assert response.status_code == 404
    assert response.json()["code"] == "network_not_found"


def test_delete_removes_aws_resources_and_record(client, auth, payload, ec2_client):
    created = client.post("/v1/networks", json=payload, headers=auth).json()
    network_id = created["network_id"]

    assert client.delete(f"/v1/networks/{network_id}", headers=auth).status_code == 204

    assert managed_vpcs(ec2_client) == []
    assert managed_subnets(ec2_client) == []
    assert ec2_client.describe_internet_gateways()["InternetGateways"] == []
    assert client.get(f"/v1/networks/{network_id}", headers=auth).status_code == 404


def test_delete_unknown_network_returns_404(client, auth):
    assert client.delete("/v1/networks/nope", headers=auth).status_code == 404
