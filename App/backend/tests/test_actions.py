"""Tests for POST /actions."""

from sqlalchemy import text


def test_anonymous_blocked(client):
    r = client.post("/actions", data={"action_type": "close_borehole", "station_id": "1"})
    assert r.status_code in (302, 403)


def test_medical_blocked(med_session):
    r = med_session.post("/actions", data={"action_type": "close_borehole", "station_id": "1"})
    assert r.status_code == 403


def test_gov_can_close_borehole(gov_session):
    r = gov_session.post("/actions", data={
        "action_type": "close_borehole",
        "station_id": "1",
    })
    assert r.status_code == 302  # redirect back

    from database import connection
    with connection() as c:
        row = c.execute(text("SELECT is_closed FROM stations WHERE station_id = 1")).fetchone()
        assert row[0] == 1
        iv = c.execute(
            text("SELECT action_type, triggered_by FROM interventions ORDER BY intervention_id DESC LIMIT 1")
        ).fetchone()
        assert iv[0] == "close_borehole"
        assert iv[1] == "official.jones"


def test_double_close_rejected(gov_session):
    gov_session.post("/actions", data={"action_type": "close_borehole", "station_id": "1"})
    r = gov_session.post("/actions", data={"action_type": "close_borehole", "station_id": "1"})
    assert r.status_code == 400


def test_reopen_only_when_closed(gov_session):
    r = gov_session.post("/actions", data={"action_type": "reopen_borehole", "station_id": "1"})
    assert r.status_code == 400  # station is open already


def test_close_then_reopen_succeeds(gov_session):
    gov_session.post("/actions", data={"action_type": "close_borehole", "station_id": "1"})
    r = gov_session.post("/actions", data={"action_type": "reopen_borehole", "station_id": "1"})
    assert r.status_code == 302
    from database import connection
    with connection() as c:
        row = c.execute(text("SELECT is_closed FROM stations WHERE station_id = 1")).fetchone()
        assert row[0] == 0


def test_dispatch_sample_team_always_allowed(gov_session):
    r = gov_session.post("/actions", data={
        "action_type": "dispatch_sample_team",
        "station_id": "2",
        "notes": "send the team",
    })
    assert r.status_code == 302
    from database import connection
    with connection() as c:
        iv = c.execute(
            text("SELECT action_type, notes FROM interventions ORDER BY intervention_id DESC LIMIT 1")
        ).fetchone()
        assert iv[0] == "dispatch_sample_team"
        assert iv[1] == "send the team"


def test_dispatch_medical_team_always_allowed(gov_session):
    r = gov_session.post("/actions", data={
        "action_type": "dispatch_medical_team",
        "station_id": "3",
    })
    assert r.status_code == 302


def test_unknown_station_rejected(gov_session):
    r = gov_session.post("/actions", data={
        "action_type": "dispatch_sample_team",
        "station_id": "999",
    })
    assert r.status_code == 400


def test_unknown_action_type_rejected(gov_session):
    r = gov_session.post("/actions", data={
        "action_type": "evict_villagers",
        "station_id": "1",
    })
    assert r.status_code == 400


def test_related_report_id_persisted(gov_session):
    from database import connection
    with connection() as c:
        with c.begin():
            cur = c.execute(
                text(
                    "INSERT INTO illness_reports (station_id, raw_message, parser_version, report_source) "
                    "VALUES (1, 'r', 'v', 'sms')"
                )
            )
            rid = cur.lastrowid
    gov_session.post("/actions", data={
        "action_type": "dispatch_medical_team",
        "station_id": "1",
        "related_report_id": str(rid),
    })
    with connection() as c:
        iv = c.execute(
            text("SELECT related_report_id FROM interventions ORDER BY intervention_id DESC LIMIT 1")
        ).fetchone()
        assert iv[0] == rid


def test_notes_truncated_to_500(gov_session):
    long_note = "x" * 1000
    gov_session.post("/actions", data={
        "action_type": "dispatch_sample_team",
        "station_id": "1",
        "notes": long_note,
    })
    from database import connection
    with connection() as c:
        iv = c.execute(text("SELECT notes FROM interventions ORDER BY intervention_id DESC LIMIT 1")).fetchone()
        assert len(iv[0]) == 500
