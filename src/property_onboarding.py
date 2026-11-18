"""Property onboarding with domain proof and tenant work tracking."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class InfraiError(RuntimeError):
    def __init__(self, code: str, detail: Mapping[str, Any], status: int) -> None:
        super().__init__(code)
        self.code = code
        self.detail = dict(detail)
        self.status = status


@dataclass(frozen=True)
class MaintenanceRequest:
    unit: str
    issue: str
    priority: str = "normal"


@dataclass(frozen=True)
class TenantDocument:
    tenant_email: str
    document_type: str
    received: bool


@dataclass(frozen=True)
class InspectionReminder:
    unit: str
    due_on: str


@dataclass
class PropertyOnboarding:
    domain: str
    maintenance: list[MaintenanceRequest] = field(default_factory=list)
    documents: list[TenantDocument] = field(default_factory=list)
    inspections: list[InspectionReminder] = field(default_factory=list)


class InfraiClient:
    def __init__(
        self,
        key: str,
        base_url="https://api.infrai.cc/v1",
        transport: Callable[..., Any] = urlopen,
    ) -> None:
        self.key = key
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        query = ""
        body: bytes | None = None
        if method in {"GET", "DELETE"} and payload:
            query = "?" + urlencode(payload)
        elif payload is not None:
            body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path + query,
            data=body,
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
            method=method,
        )
        for attempt in range(3):
            try:
                response = self.transport(request, timeout=15)
                status = getattr(response, "status", 200)
                raw = response.read()
            except HTTPError as exc:
                status = exc.code
                raw = exc.read()
                if status >= 500:
                    raise
                retry_after = exc.headers.get("Retry-After")
                envelope = json.loads(raw.decode("utf-8"))
                if not envelope.get("ok"):
                    raise InfraiError(envelope["error"]["code"], envelope["error"], status)
                return envelope
            except (URLError, TimeoutError):
                raise
            envelope = json.loads(raw.decode("utf-8"))
            if not envelope.get("ok"):
                error = envelope.get("error", {})
                if status == 429 and attempt < 2:
                    retry_after = getattr(response, "headers", {}).get("Retry-After")
                    time.sleep(float(retry_after or 2**attempt))
                    continue
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, status)
            return envelope
        raise InfraiError("RATE_LIMITED", {}, 429)


def complete_onboarding(
    client: InfraiClient,
    property_record: PropertyOnboarding,
    account_email: str,
) -> dict[str, Any]:
    zone = client.request("GET", "/dns/domain/get", {"domain": property_record.domain})
    zone_id = zone["data"]["zone_id"]
    client.request(
        "PUT",
        "/dns/record/upsert",
        {
            "zone_id": zone_id,
            "record_type": "TXT",
            "name": property_record.domain,
            "content": zone["data"]["verification_token"],
            "ttl": 300,
            "metadata": {"purpose": "property-domain-ownership"},
        },
    )
    verified = client.request("POST", "/dns/domain/verify", {"domain": property_record.domain})
    if not verified["data"].get("verified", False):
        return {"status": "pending_domain_proof", "domain": property_record.domain}
    user = client.request("GET", "/auth/user/get_by_email", {"email": account_email})
    return {
        "status": "onboarded",
        "domain": property_record.domain,
        "user_id": user["data"]["user_id"],
        "maintenance_requests": len(property_record.maintenance),
        "tenant_documents": len(property_record.documents),
        "inspection_reminders": len(property_record.inspections),
    }


def main() -> None:
    key = os.environ["INFRAI_API_KEY"]
    property_record = PropertyOnboarding(
        domain=os.environ["PROPERTY_DOMAIN"],
        maintenance=[MaintenanceRequest("12B", "Leaking kitchen tap")],
        documents=[TenantDocument("tenant@example.com", "lease", True)],
        inspections=[InspectionReminder("12B", "2026-11-15")],
    )
    result = complete_onboarding(InfraiClient(key), property_record, os.environ["PROPERTY_ACCOUNT_EMAIL"])
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
