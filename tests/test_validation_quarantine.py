"""Tests for data contract validation and quarantine store."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from api.models import RunRequest, MaterialEnum
from api.quarantine import QuarantineStore
from api.main import app


def test_valid_request_contract():
    req = RunRequest(
        description="Stainless steel vacuum flask with a moulded plastic outer body.",
        materials=[MaterialEnum.STAINLESS_STEEL, MaterialEnum.PLASTIC],
        intended_use="Insulated beverage container",
    )
    assert req.description.startswith("Stainless steel")
    assert MaterialEnum.STAINLESS_STEEL in req.materials


def test_cross_field_validation_failure():
    # Description mentions steel, but materials only declares plastic
    with pytest.raises(ValidationError) as exc_info:
        RunRequest(
            description="High grade steel cutlery set for restaurant dining.",
            materials=[MaterialEnum.PLASTIC],
        )
    assert "Description mentions 'steel'" in str(exc_info.value)


def test_quarantine_on_invalid_request(tmp_path):
    db_path = str(tmp_path / "test_quarantine.db")
    store = QuarantineStore(db_path=db_path)
    assert store.count() == 0

    record_id = store.quarantine(
        raw_payload={"description": "tiny", "materials": []},
        validation_errors=[{"loc": ["description"], "msg": "too short"}],
        correlation_id="test-corr-123",
    )
    assert record_id == 1
    assert store.count() == 1

    records = store.list_quarantined()
    assert len(records) == 1
    assert records[0]["correlation_id"] == "test-corr-123"
    assert records[0]["validation_errors"][0]["loc"] == ["description"]


def test_invalid_request_returns_422_and_no_job_enqueued():
    client = TestClient(app)
    # Payload with description < 10 characters and empty materials
    invalid_payload = {
        "description": "Short",
        "materials": [],
    }
    response = client.post("/runs", json=invalid_payload)
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
    assert "quarantined" in data["message"].lower()
