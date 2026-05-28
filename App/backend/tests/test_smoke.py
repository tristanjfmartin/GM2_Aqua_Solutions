def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_anonymous_root_redirects_to_login(client):
    r = client.get("/")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_gov_session_can_reach_dashboard(gov_session):
    r = gov_session.get("/dashboard")
    assert r.status_code == 200
    assert b"Station status" in r.data


def test_med_session_blocked_from_dashboard(med_session):
    r = med_session.get("/dashboard")
    assert r.status_code == 403
