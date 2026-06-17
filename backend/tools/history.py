"""DynamoDB-backed per-user scan history.

Schema (single table ``SCAN_HISTORY``):
  userId  (PK, S)  — Cognito email; isolates each user's data.
  scanId  (SK, S)  — ``<createdAt>#<uuid8>``; querying with ScanIndexForward=False yields
                     newest-first because the ISO8601 prefix sorts lexicographically.
``summary``/``report``/``gate`` are JSON-serialized strings (DynamoDB rejects raw floats),
parsed back to objects on read.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

_JSON_FIELDS = ("summary", "report", "gate")


class ScanHistory:
    def __init__(self, table_name: str, region: Optional[str] = None, resource=None):
        self.table_name = table_name
        self._resource = resource
        self._region = region

    @property
    def table(self):
        if self._resource is None:
            import boto3

            self._resource = boto3.resource("dynamodb", region_name=self._region)
        return self._resource.Table(self.table_name)

    def save_scan(
        self,
        user_id: str,
        scan_id: str,
        created_at: str,
        project_path: str,
        max_files: int,
        pass_at_k: int,
        status: str = "done",
        summary: Optional[Dict] = None,
        report: Optional[Dict] = None,
        gate: Optional[Dict] = None,
    ) -> Dict:
        item = {
            "userId": user_id,
            "scanId": scan_id,
            "createdAt": created_at,
            "projectPath": project_path,
            "maxFiles": max_files,
            "passAtK": pass_at_k,
            "status": status,
            "summary": json.dumps(summary or {}, ensure_ascii=False),
            "report": json.dumps(report or {}, ensure_ascii=False),
            "gate": json.dumps(gate or {}, ensure_ascii=False),
        }
        self.table.put_item(Item=item)
        return item

    def update_status(self, user_id: str, scan_id: str, **fields) -> None:
        """Patch an existing scan record (used by async mode to advance status/result)."""
        if not fields:
            return
        sets, names, values = [], {}, {}
        for i, (k, v) in enumerate(fields.items()):
            if k in _JSON_FIELDS:
                v = json.dumps(v or {}, ensure_ascii=False)
            sets.append(f"#k{i} = :v{i}")
            names[f"#k{i}"] = k
            values[f":v{i}"] = v
        self.table.update_item(
            Key={"userId": user_id, "scanId": scan_id},
            UpdateExpression="SET " + ", ".join(sets),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def list_history(self, user_id: str, limit: int = 50) -> List[Dict]:
        from boto3.dynamodb.conditions import Key

        resp = self.table.query(
            KeyConditionExpression=Key("userId").eq(user_id),
            ScanIndexForward=False,  # newest first
            Limit=limit,
        )
        return [self._decode(i) for i in resp.get("Items", [])]

    def get_scan(self, user_id: str, scan_id: str) -> Optional[Dict]:
        resp = self.table.get_item(Key={"userId": user_id, "scanId": scan_id})
        item = resp.get("Item")
        return self._decode(item) if item else None

    @staticmethod
    def _decode(item: Dict) -> Dict:
        out = dict(item)
        for f in _JSON_FIELDS:
            if isinstance(out.get(f), str):
                try:
                    out[f] = json.loads(out[f])
                except ValueError:
                    pass
        # DynamoDB returns numbers as Decimal — coerce the known ints
        for f in ("maxFiles", "passAtK"):
            if f in out:
                try:
                    out[f] = int(out[f])
                except (TypeError, ValueError):
                    pass
        return out
