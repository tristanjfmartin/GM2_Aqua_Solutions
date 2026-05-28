from sqlalchemy import text


def _insert_report(station_id=1):
    from database import connection
    with connection() as c:
        with c.begin():
            cur = c.execute(
                text(
                    "INSERT INTO illness_reports (station_id, raw_message, parser_version, report_source) "
                    "VALUES (:sid, 'station x', 'v', 'sms')"
                ),
                {"sid": station_id},
            )
            return cur.lastrowid


def test_detail_page_has_action_buttons(gov_session):
    rid = _insert_report()
    r = gov_session.get(f"/dashboard/reports/{rid}")
    body = r.data.decode("utf-8")
    assert "close_borehole" in body
    assert "dispatch_sample_team" in body
    assert "dispatch_medical_team" in body
    assert str(rid) in body


def test_action_from_detail_records_related_report(gov_session):
    rid = _insert_report()
    gov_session.post("/actions", data={
        "action_type": "dispatch_sample_team",
        "station_id": "1",
        "related_report_id": str(rid),
    })
    from database import connection
    with connection() as c:
        iv = c.execute(
            text("SELECT related_report_id FROM interventions ORDER BY intervention_id DESC LIMIT 1")
        ).fetchone()
        assert iv[0] == rid


def test_detail_shows_interventions_for_this_report(gov_session):
    rid = _insert_report()
    gov_session.post("/actions", data={
        "action_type": "dispatch_sample_team",
        "station_id": "1",
        "related_report_id": str(rid),
        "notes": "investigate immediately",
    })
    r = gov_session.get(f"/dashboard/reports/{rid}")
    body = r.data.decode("utf-8")
    assert "dispatch_sample_team" in body
    assert "investigate immediately" in body
    assert "official.jones" in body
