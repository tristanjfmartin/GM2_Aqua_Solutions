"""Tests for /medical/reports/<id> — medical-side read-only detail page."""

import json

from sqlalchemy import text


def _insert_medical_report():
    from database import connection
    with connection() as c:
        with c.begin():
            cur = c.execute(
                text(
                    "INSERT INTO illness_reports (station_id, raw_message, parser_version, "
                    "report_source, submitter, case_count, symptoms, risk_tier) "
                    "VALUES (1, 'test', 'v', 'medical_portal', 'dr.smith', 4, :sym, 'high')"
                ),
                {"sym": json.dumps(["diarrhoea", "fever"])},
            )
            return cur.lastrowid


def test_anonymous_redirected_to_login(client):
    rid = _insert_medical_report()
    r = client.get(f"/medical/reports/{rid}", follow_redirects=False)
    assert r.status_code == 302


def test_government_user_blocked(gov_session):
    rid = _insert_medical_report()
    r = gov_session.get(f"/medical/reports/{rid}")
    assert r.status_code == 403


def test_medical_user_sees_report(med_session):
    rid = _insert_medical_report()
    r = med_session.get(f"/medical/reports/{rid}")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Borehole A" in body
    assert "diarrhoea" in body
    assert "fever" in body


def test_no_action_buttons_on_medical_detail(med_session):
    rid = _insert_medical_report()
    r = med_session.get(f"/medical/reports/{rid}")
    body = r.data.decode("utf-8")
    assert "action_type" not in body  # no /actions form on medical page
    assert "Close" not in body or "Reopen" not in body


def test_no_estimator_banner_on_medical_detail(med_session):
    """Medical detail never shows the 'not medical advice' banner."""
    rid = _insert_medical_report()
    r = med_session.get(f"/medical/reports/{rid}")
    body = r.data.decode("utf-8")
    assert "Estimated by automated heuristic" not in body
