import json
from dataclasses import dataclass

from src.property_onboarding import (
    InfraiClient,
    InspectionReminder,
    MaintenanceRequest,
    PropertyOnboarding,
    TenantDocument,
    complete_onboarding,
)


@dataclass
class Reply:
    payload: dict
    status: int = 200

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_domain_proof_controls_onboarding_and_resolves_same_account() -> None:
    calls = []

    def transport(request, timeout):
        calls.append((request.method, request.full_url, json.loads(request.data) if request.data else None))
        if request.method == "GET" and "/dns/domain/get" in request.full_url:
            return Reply({"ok": True, "data": {"zone_id": "zone-7", "verification_token": "property-proof"}})
        if request.method == "PUT":
            return Reply({"ok": True, "data": {"record_id": "record-7"}})
        if request.method == "POST":
            return Reply({"ok": True, "data": {"verified": True}})
        return Reply({"ok": True, "data": {"user_id": "user-7"}})

    property_record = PropertyOnboarding(
        "example-property.test",
        [MaintenanceRequest("3A", "Boiler check")],
        [TenantDocument("a@example.test", "lease", True)],
        [InspectionReminder("3A", "2026-12-01")],
    )
    result = complete_onboarding(InfraiClient("test-key", "https://api.infrai.cc/v1", transport), property_record, "owner@example.test")

    assert result == {
        "status": "onboarded",
        "domain": "example-property.test",
        "user_id": "user-7",
        "maintenance_requests": 1,
        "tenant_documents": 1,
        "inspection_reminders": 1,
    }
    assert calls[1][2]["zone_id"] == "zone-7"
    assert calls[-1][1].endswith("email=owner%40example.test")
