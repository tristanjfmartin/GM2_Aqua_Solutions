"""Tests for /medical/history."""

import json
import re

from sqlalchemy import text


def _insert_medical_reports(n=3):
    from database import connection
    with connection() as c:
        with c.begin():
            for i in range(n):
                c.execute(
                    text(
                        "INSERT INTO illness_reports (station_id, raw_message, parser_version, "
                        "report_source, submitter, case_count, symptoms, risk_tier) "
                        "VALUES (:sid, :msg, :pv, 'medical_portal', 'dr.smith', :cc, :sym, :rt)"
                    ),
                    {
                        "sid": (i % 4) + 1,
                        "msg": f"report {i}",
                        "pv": "v",
                        "cc": i + 1,
                        "sym": json.dumps(["diarrhoea"]),
                        "rt": ["low", "medium", "high"][i % 3],
                    },
                )


def test_anonymous_blocked(client):
    r = client.get("/medical/history", follow_redirects=False)
    assert r.status_code == 302


def test_government_user_blocked(gov_session):
    r = gov_session.get("/medical/history")
    assert r.status_code == 403


def test_medical_user_sees_history(med_session):
    _insert_medical_reports(3)
    r = med_session.get("/medical/history")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "History" in body or "history" in body.lower()


def test_history_shows_reports(med_session):
    _insert_medical_reports(2)
    r = med_session.get("/medical/history")
    body = r.data.decode("utf-8")
    assert body.count("dr.smith") >= 2


def test_history_excludes_sms_reports(med_session):
    from database import connection
    _insert_medical_reports(1)
    with connection() as c:
        with c.begin():
            c.execute(
                text(
                    "INSERT INTO illness_reports (station_id, raw_message, parser_version, "
                    "report_source, reporter_phone) "
                    "VALUES (1, 'station 1', 'v', 'sms', '+1555')"
                )
            )
    r = med_session.get("/medical/history")
    body = r.data.decode("utf-8")
    assert "+1555" not in body
    assert "1555" not in body


def test_history_includes_leaflet_map(med_session):
    r = med_session.get("/medical/history")
    body = r.data.decode("utf-8")
    assert "leaflet" in body.lower()
    assert "-17.82" in body or "-17.83" in body
    assert "31.05" in body
