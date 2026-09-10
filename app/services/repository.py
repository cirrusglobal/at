"""DynamoDB persistence for provisioned networks.

Single table keyed on `network_id`, plus a GSI that supports ordered listing.
The GSI exists so listing never needs a `scan`: every item carries a constant
`entity_type` partition key with `created_at` as the sort key, which gives
newest-first pagination at predictable cost.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from boto3.dynamodb.conditions import Key

LIST_INDEX_NAME = "by_created_at"
ENTITY_TYPE = "network"


def build_table(dynamodb: Any, table_name: str, create_if_missing: bool = True) -> Any:
    """Return the table, optionally creating it when absent.

    Creation is for local development and tests only. Deployed environments get
    the table from Terraform, and pass create_if_missing=False so the runtime
    role needs neither ListTables nor CreateTable.
    """
    if not create_if_missing:
        return dynamodb.Table(table_name)

    existing = {t.name for t in dynamodb.tables.all()}
    if table_name not in existing:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "network_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "network_id", "AttributeType": "S"},
                {"AttributeName": "entity_type", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": LIST_INDEX_NAME,
                    "KeySchema": [
                        {"AttributeName": "entity_type", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamodb.meta.client.get_waiter("table_exists").wait(TableName=table_name)
    return dynamodb.Table(table_name)


def _encode_cursor(key: dict | None) -> str | None:
    if not key:
        return None
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode()


def _decode_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, TypeError) as exc:
        raise ValueError("malformed cursor") from exc


class NetworkRepository:
    def __init__(self, table: Any) -> None:
        self._table = table

    def put(self, record: dict) -> None:
        self._table.put_item(Item={**record, "entity_type": ENTITY_TYPE})

    def get(self, network_id: str) -> dict | None:
        response = self._table.get_item(Key={"network_id": network_id})
        item = response.get("Item")
        return _strip_internal(item) if item else None

    def list(self, limit: int = 25, cursor: str | None = None) -> tuple[list[dict], str | None]:
        kwargs: dict[str, Any] = {
            "IndexName": LIST_INDEX_NAME,
            "KeyConditionExpression": Key("entity_type").eq(ENTITY_TYPE),
            "ScanIndexForward": False,  # newest first
            "Limit": limit,
        }
        start_key = _decode_cursor(cursor)
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key

        response = self._table.query(**kwargs)
        items = [_strip_internal(item) for item in response.get("Items", [])]
        return items, _encode_cursor(response.get("LastEvaluatedKey"))

    def delete(self, network_id: str) -> None:
        self._table.delete_item(Key={"network_id": network_id})


def _strip_internal(item: dict) -> dict:
    """Drop attributes that exist only to support indexing."""
    return {k: v for k, v in item.items() if k != "entity_type"}
