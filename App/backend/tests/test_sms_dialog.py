"""Tests for the multi-turn SMS dialog at /sms."""

import re

from sqlalchemy import text


def _sms(client, body, frm="+15551234567"):
    return client.post("/sms", data={"From": frm, "Body": body})


def _last_report(phone="+15551234567"):
    from database import connection
    with connection() as c:
        return c.execute(
            text(
                "SELECT * FROM illness_reports WHERE reporter_phone = :phone "
                "ORDER BY report_id DESC LIMIT 1"
            ),
            {"phone": phone},
        ).mappings().fetchone()


def test_first_sms_with_station_starts_conversation(client):
    r = _sms(client, "station 4")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "How many people are sick" in body
    row = _last_report()
    assert row["station_id"] == 4
    assert row["dialog_state"] == "awaiting_case_count"


def test_unparseable_first_sms_asks_for_station(client):
    r = _sms(client, "help me")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "station number" in body.lower()
    row = _last_report()
    assert row["station_id"] is None
    assert row["dialog_state"] is None


def test_case_count_step(client):
    _sms(client, "station 4")
    r = _sms(client, "5")
    body = r.data.decode("utf-8")
    assert "5 cases" in body
    assert "symptoms" in body.lower()
    row = _last_report()
    assert row["case_count"] == 5
    assert row["dialog_state"] == "awaiting_symptoms"


def test_symptoms_step(client):
    _sms(client, "station 4")
    _sms(client, "3")
    r = _sms(client, "1,3")
    body = r.data.decode("utf-8")
    assert "diarrhoea" in body and "fever" in body
    assert "When did symptoms start" in body
    row = _last_report()
    import json
    assert json.loads(row["symptoms"]) == ["diarrhoea", "fever"]
    assert row["dialog_state"] == "awaiting_onset"


def test_complete_conversation(client):
    _sms(client, "station 4")
    _sms(client, "3")
    _sms(client, "1,3")
    r = _sms(client, "today")
    body = r.data.decode("utf-8")
    assert "Report complete" in body
    row = _last_report()
    assert row["dialog_state"] == "complete"
    assert row["onset_date"] is not None


def test_stop_keyword_abandons(client):
    _sms(client, "station 4")
    r = _sms(client, "STOP")
    body = r.data.decode("utf-8")
    assert "Opted out" in body
    row = _last_report()
    assert row["dialog_state"] == "abandoned"


def test_stop_with_no_conversation_is_idempotent(client):
    r = _sms(client, "STOP")
    body = r.data.decode("utf-8")
    assert "No active conversation" in body


def test_unparseable_case_count_re_prompts(client):
    _sms(client, "station 4")
    r = _sms(client, "nope")
    body = r.data.decode("utf-8")
    assert "I didn't understand" in body
    row = _last_report()
    assert row["dialog_state"] == "awaiting_case_count"  # unchanged


def test_new_station_mid_conversation_abandons_old(client):
    _sms(client, "station 4")
    _sms(client, "3")  # awaiting_symptoms now
    r = _sms(client, "station 7")
    body = r.data.decode("utf-8")
    assert "station 7" in body.lower() or "Borehole G" in body
    from database import connection
    with connection() as c:
        rows = c.execute(
            text(
                "SELECT station_id, dialog_state FROM illness_reports "
                "WHERE reporter_phone = '+15551234567' ORDER BY report_id"
            )
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == 4
        assert rows[0][1] == "abandoned"
        assert rows[1][0] == 7
        assert rows[1][1] == "awaiting_case_count"


def test_labelling_fires_on_first_sms_only(client):
    """Insert a sensor reading so labelling has something to label."""
    from database import connection
    from datetime import datetime, timezone, timedelta
    with connection() as c:
        with c.begin():
            ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            c.execute(
                text(
                    "INSERT INTO sensor_readings (station_id, recorded_at, ph, turbidity_ntu, "
                    "temperature_c, rainfall_mm, provenance) "
                    "VALUES (4, :ts, 7.0, 5.0, 22.0, 0.0, 'test')"
                ),
                {"ts": ts},
            )
    _sms(client, "station 4")
    with connection() as c:
        labels_after_first = c.execute(text("SELECT COUNT(*) FROM reading_labels")).fetchone()[0]
    _sms(client, "3")
    _sms(client, "1,3")
    _sms(client, "today")
    with connection() as c:
        labels_after_complete = c.execute(text("SELECT COUNT(*) FROM reading_labels")).fetchone()[0]
    assert labels_after_first == labels_after_complete  # no extra labels added by dialog
