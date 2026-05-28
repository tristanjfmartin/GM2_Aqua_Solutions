import json
from datetime import date

from sqlalchemy import text


def test_dashboard_reports_panel_has_risk_tier_column(gov_session):
    """The right panel should include a Risk tier column header."""
    r = gov_session.get("/dashboard")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Risk tier" in body or "risk tier" in body.lower()


def test_dashboard_report_row_links_to_detail(gov_session):
    """Every report row in the right panel links to /dashboard/reports/<id>."""
    from database import connection
    with connection() as c:
        with c.begin():
            cur = c.execute(
                text(
                    "INSERT INTO illness_reports (station_id, raw_message, parser_version, report_source) "
                    "VALUES (1, 'station 1', 'v', 'sms')"
                )
            )
            rid = cur.lastrowid
    r = gov_session.get("/dashboard")
    body = r.data.decode("utf-8")
    assert f"/dashboard/reports/{rid}" in body


def test_dashboard_shows_reporter_tier_when_set(gov_session):
    """A report row with a reporter-supplied tier shows a bright pill."""
    from database import connection
    with connection() as c:
        with c.begin():
            c.execute(
                text(
                    "INSERT INTO illness_reports (station_id, raw_message, parser_version, "
                    "report_source, risk_tier) "
                    "VALUES (1, 't', 'v', 'medical_portal', 'severe')"
                )
            )
    r = gov_session.get("/dashboard")
    body = r.data.decode("utf-8")
    assert "SEVERE" in body  # uppercase tier in pill
