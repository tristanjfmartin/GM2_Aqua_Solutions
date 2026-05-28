"""Tests for /medical/report — the risk-tier dropdown and its persistence."""


def test_form_renders_risk_tier_dropdown(med_session):
    r = med_session.get("/medical/report")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    # All five options must be in the form
    assert 'name="risk_tier"' in body
    assert 'value=""' in body                    # "Not yet assessed"
    assert 'value="low"' in body
    assert 'value="medium"' in body
    assert 'value="high"' in body
    assert 'value="severe"' in body


def test_submitting_with_risk_tier_persists_it(med_session):
    from sqlalchemy import text
    r = med_session.post("/medical/report", data={
        "station_id": "1",
        "case_count": "3",
        "symptoms": ["diarrhoea"],
        "onset_date": "",
        "notes": "",
        "risk_tier": "high",
    })
    assert r.status_code == 200
    from database import connection
    with connection() as c:
        row = c.execute(text("SELECT risk_tier FROM illness_reports ORDER BY report_id DESC LIMIT 1")).fetchone()
        assert row[0] == "high"


def test_submitting_without_risk_tier_stores_null(med_session):
    from sqlalchemy import text
    r = med_session.post("/medical/report", data={
        "station_id": "2",
        "case_count": "1",
        "symptoms": [],
        "onset_date": "",
        "notes": "",
        "risk_tier": "",
    })
    assert r.status_code == 200
    from database import connection
    with connection() as c:
        row = c.execute(text("SELECT risk_tier FROM illness_reports ORDER BY report_id DESC LIMIT 1")).fetchone()
        assert row[0] is None


def test_submitting_bogus_risk_tier_is_rejected(med_session):
    r = med_session.post("/medical/report", data={
        "station_id": "1",
        "case_count": "1",
        "symptoms": [],
        "onset_date": "",
        "notes": "",
        "risk_tier": "bogus_value",
    })
    # Should be rejected at render-time validation, not crash on DB CHECK.
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "error" in body.lower() or "invalid" in body.lower()
