# Medical history, gov detail + actions, SMS dialog — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the four-phase design in `docs/superpowers/specs/2026-05-28-medical-gov-portal-design.md` — `/medical/history` with a Harare-centred Leaflet map (Phase C), government per-report detail page with a risk-tier estimator (Phase D), action buttons backed by an interventions table (Phase E), and a multi-turn SMS dialog that progressively enriches SMS reports (Phase F).

**Architecture:** All four phases add to the existing Flask + SQLite + Twilio backend in `App/backend/`. Schema changes use the idempotent `_migrate(conn)` pattern already in `database.py`. The estimator is a pure function in a new `estimator.py` module so it can be unit-tested without Flask. SMS dialog state is encoded in `illness_reports.dialog_state`; the `/sms` route becomes a small state machine. The dashboard right panel becomes a feed of clickable links to per-report detail pages.

**Tech Stack:** Python 3, Flask 3.0, SQLite (built-in), Twilio Python SDK 9.3, `python-dotenv`, Jinja2 templates, Leaflet 1.9.4 (CDN), pytest (added in this plan for TDD).

**Implementation order:** D → C → E → F (per spec §10). Each phase committable independently.

---

## Pre-flight — Task 0: pytest setup with scratch-DB fixture

Existing codebase has no pytest harness. We add one so every TDD step in this plan is real. The fixture creates a scratch SQLite DB per test, runs `init_db()` against it, and yields a Flask test client.

**Files:**
- Modify: `App/backend/requirements.txt`
- Create: `App/backend/conftest.py`
- Create: `App/backend/tests/__init__.py` (empty)
- Create: `App/backend/tests/test_smoke.py`

- [ ] **Step 1: Add pytest to requirements.txt**

Modify `App/backend/requirements.txt`. Append:

```
pytest==8.3.3
```

- [ ] **Step 2: Install pytest into the existing venv**

```bash
cd App/backend
source .venv/bin/activate
pip install -r requirements.txt
```

Expected: `Successfully installed pytest-8.3.3 ...`. Verify with `pytest --version`.

- [ ] **Step 3: Write conftest.py with the scratch-DB fixture**

Create `App/backend/conftest.py`:

```python
"""Pytest fixtures.

Each test gets its own fresh SQLite DB at a tempfile path. The Flask
app reads DATABASE_PATH from os.environ at connection time
(see database.py), so we override it before importing the app.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def tmp_db_path(monkeypatch):
    """Per-test scratch SQLite DB file. Cleaned up on teardown."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_PATH", path)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("MEDICAL_PASSWORD", "med-pw")
    monkeypatch.setenv("GOV_PASSWORD", "gov-pw")
    monkeypatch.setenv("DEVICE_SECRET", "test-device-secret")
    monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURES", "false")
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@pytest.fixture()
def app(tmp_db_path):
    """Fresh Flask app bound to the scratch DB. Re-imports so module
    state (DEMO_USERS, init_db) is rebuilt against the new env."""
    for mod in ("app", "database", "labels", "sensor_ingest"):
        sys.modules.pop(mod, None)
    import app as app_mod
    return app_mod.app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def gov_session(client):
    """Test client with the government user signed in."""
    client.post("/login", data={"username": "official.jones", "password": "gov-pw"})
    return client


@pytest.fixture()
def med_session(client):
    """Test client with the medical user signed in."""
    client.post("/login", data={"username": "dr.smith", "password": "med-pw"})
    return client
```

- [ ] **Step 4: Write a smoke test to prove the fixture works**

Create `App/backend/tests/__init__.py` (empty file).

Create `App/backend/tests/test_smoke.py`:

```python
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
```

- [ ] **Step 5: Run the smoke tests**

```bash
cd App/backend
.venv/bin/pytest tests/test_smoke.py -v
```

Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
git add App/backend/requirements.txt App/backend/conftest.py App/backend/tests/__init__.py App/backend/tests/test_smoke.py
git commit -m "Add pytest with scratch-DB fixture for TDD"
```

---

## Phase D — risk-tier estimator, gov detail page, diagnosis dropdown

### Task D.1: Schema migration — add `risk_tier` to `illness_reports`

**Files:**
- Modify: `App/backend/database.py`
- Modify: `App/backend/tests/__init__.py`
- Create: `App/backend/tests/test_migrations.py`

- [ ] **Step 1: Write the failing test**

Create `App/backend/tests/test_migrations.py`:

```python
def test_illness_reports_has_risk_tier_column(app):
    """risk_tier must exist on illness_reports; NULL allowed; CHECK enforced."""
    from database import connection
    with connection() as c:
        cols = {r["name"]: r for r in c.execute("PRAGMA table_info(illness_reports)").fetchall()}
        assert "risk_tier" in cols
        # CHECK is enforced at INSERT time
        c.execute(
            "INSERT INTO illness_reports (raw_message, parser_version, risk_tier) "
            "VALUES ('test', 'v', 'low')"
        )
        c.execute(
            "INSERT INTO illness_reports (raw_message, parser_version, risk_tier) "
            "VALUES ('test', 'v', NULL)"
        )
        import sqlite3
        try:
            c.execute(
                "INSERT INTO illness_reports (raw_message, parser_version, risk_tier) "
                "VALUES ('test', 'v', 'bogus')"
            )
            assert False, "CHECK constraint should have rejected 'bogus'"
        except sqlite3.IntegrityError:
            pass
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_migrations.py::test_illness_reports_has_risk_tier_column -v
```

Expected: FAIL (`risk_tier` not in cols).

- [ ] **Step 3: Add the migration**

Modify `App/backend/database.py`. Find the `_migrate(conn)` function and extend the `added_columns` list with the new entry:

```python
    added_columns = [
        ("report_source", "TEXT NOT NULL DEFAULT 'sms'"),
        ("submitter",     "TEXT"),
        ("case_count",    "INTEGER"),
        ("onset_date",    "TEXT"),
        ("symptoms",      "TEXT"),
        ("risk_tier",     "TEXT CHECK (risk_tier IN ('low','medium','high','severe'))"),
    ]
```

Also extend the `SCHEMA` string (for fresh DBs) — locate the `CREATE TABLE IF NOT EXISTS illness_reports` block and add the column inside the parentheses, just before the closing `)`:

```sql
    symptoms          TEXT,
    risk_tier         TEXT CHECK (risk_tier IN ('low','medium','high','severe'))
```

- [ ] **Step 4: Run to verify pass**

```bash
.venv/bin/pytest tests/test_migrations.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add App/backend/database.py App/backend/tests/test_migrations.py
git commit -m "Phase D: add risk_tier column to illness_reports"
```

### Task D.2: Estimator function — tests

The cholera-pattern heuristic is a pure function. Write tests first.

**Files:**
- Create: `App/backend/tests/test_estimator.py`

- [ ] **Step 1: Write the failing tests**

Create `App/backend/tests/test_estimator.py`:

```python
"""Tests for the cholera-pattern risk-tier estimator.

Spec: docs/superpowers/specs/2026-05-28-medical-gov-portal-design.md §5.
Rules in priority order: SEVERE, HIGH, MEDIUM, LOW (first match wins).
"""

from datetime import date, timedelta

import pytest

from estimator import estimate_risk_tier


TODAY = date.today()


# --- SEVERE rule -----------------------------------------------------------

def test_severe_textbook_cholera_pattern():
    tier, rationale = estimate_risk_tier(
        symptoms=["diarrhoea", "dehydration"],
        onset_date=TODAY - timedelta(days=2),
        case_count=4,
    )
    assert tier == "severe"
    assert "textbook" in rationale.lower() or "severe-cholera" in rationale.lower()


def test_severe_requires_recent_onset():
    """Same symptoms but onset >3 days ago → not SEVERE (falls to HIGH)."""
    tier, _ = estimate_risk_tier(
        symptoms=["diarrhoea", "dehydration"],
        onset_date=TODAY - timedelta(days=10),
        case_count=4,
    )
    assert tier != "severe"


def test_severe_requires_multiple_cases():
    """Even classic symptom pattern with case_count=1 is not SEVERE."""
    tier, _ = estimate_risk_tier(
        symptoms=["diarrhoea", "dehydration"],
        onset_date=TODAY,
        case_count=1,
    )
    assert tier != "severe"


# --- HIGH rule -------------------------------------------------------------

def test_high_three_symptoms():
    tier, _ = estimate_risk_tier(
        symptoms=["diarrhoea", "vomiting", "fever"],
        onset_date=None,
        case_count=1,
    )
    assert tier == "high"


def test_high_outbreak_scale_multi_symptom():
    tier, _ = estimate_risk_tier(
        symptoms=["vomiting", "fever"],
        onset_date=None,
        case_count=8,
    )
    assert tier == "high"


def test_high_recent_diarrhoea():
    tier, _ = estimate_risk_tier(
        symptoms=["diarrhoea"],
        onset_date=TODAY - timedelta(days=1),
        case_count=1,
    )
    assert tier == "high"


# --- MEDIUM rule -----------------------------------------------------------

def test_medium_one_symptom():
    tier, rationale = estimate_risk_tier(
        symptoms=["fever"],
        onset_date=None,
        case_count=1,
    )
    assert tier == "medium"
    assert "1" in rationale or "non-specific" in rationale.lower()


def test_medium_two_symptoms_no_recent_onset():
    tier, _ = estimate_risk_tier(
        symptoms=["vomiting", "fever"],
        onset_date=None,
        case_count=1,
    )
    assert tier == "medium"


# --- LOW rule --------------------------------------------------------------

def test_low_no_symptoms():
    tier, rationale = estimate_risk_tier(
        symptoms=[],
        onset_date=None,
        case_count=1,
    )
    assert tier == "low"
    assert "no symptoms" in rationale.lower() or "clinical assessment" in rationale.lower()


# --- Defensive handling ---------------------------------------------------

def test_future_onset_date_treated_as_none():
    """Future onset_date should not satisfy the 'recent onset' rule."""
    tier, _ = estimate_risk_tier(
        symptoms=["diarrhoea", "dehydration"],
        onset_date=TODAY + timedelta(days=5),
        case_count=4,
    )
    # Without recent onset, SEVERE rule fails; falls through.
    assert tier != "severe"


def test_zero_case_count_treated_as_one():
    """case_count=0 should not trigger the multi-case rules."""
    tier, _ = estimate_risk_tier(
        symptoms=["vomiting"],
        onset_date=None,
        case_count=0,
    )
    assert tier == "medium"  # 1 symptom → MEDIUM, not HIGH


def test_negative_case_count_treated_as_one():
    tier, _ = estimate_risk_tier(
        symptoms=[],
        onset_date=None,
        case_count=-5,
    )
    assert tier == "low"


def test_unknown_symptoms_ignored():
    """Unknown symptom names should not be counted."""
    tier, _ = estimate_risk_tier(
        symptoms=["unknown_thing", "another_one"],
        onset_date=None,
        case_count=1,
    )
    assert tier == "low"


# --- Output contract -------------------------------------------------------

@pytest.mark.parametrize("symptoms,onset,cases", [
    ([], None, 1),
    (["fever"], None, 1),
    (["diarrhoea", "vomiting", "fever"], None, 1),
    (["diarrhoea", "dehydration"], TODAY, 5),
])
def test_returns_tuple_of_str(symptoms, onset, cases):
    tier, rationale = estimate_risk_tier(symptoms=symptoms, onset_date=onset, case_count=cases)
    assert tier in ("low", "medium", "high", "severe")
    assert isinstance(rationale, str)
    assert len(rationale) > 0
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_estimator.py -v
```

Expected: FAIL on import (`No module named 'estimator'`).

- [ ] **Step 3: Commit (tests only, before implementation)**

```bash
git add App/backend/tests/test_estimator.py
git commit -m "Phase D: tests for risk-tier estimator (red)"
```

### Task D.3: Estimator function — implementation

**Files:**
- Create: `App/backend/estimator.py`

- [ ] **Step 1: Implement the estimator**

Create `App/backend/estimator.py`:

```python
"""Risk-tier estimator (cholera-pattern heuristic).

Spec: docs/superpowers/specs/2026-05-28-medical-gov-portal-design.md §5.

Pure function. No DB access. Idempotent. Re-evaluated at render time
on the government detail page when the reporter did not supply a tier.

NOT a medical-advice system. The tier reflects 'does this symptom pattern
match the disease we are watching for' — not a diagnosis. The detail page
always renders an explicit 'estimated heuristic — not medical advice'
banner when this function's output is shown.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

KNOWN_SYMPTOMS = {"diarrhoea", "vomiting", "fever", "dehydration"}
RECENT_ONSET_DAYS = 3


def _normalise(
    symptoms: Iterable[str],
    onset_date: date | None,
    case_count: int,
) -> tuple[set[str], date | None, int]:
    """Defensive input handling — see spec §5 'Defensive handling'."""
    canonical = {s for s in symptoms if isinstance(s, str)} & KNOWN_SYMPTOMS
    today = date.today()
    safe_onset = onset_date if (isinstance(onset_date, date) and onset_date <= today) else None
    safe_cases = case_count if (isinstance(case_count, int) and case_count >= 1) else 1
    return canonical, safe_onset, safe_cases


def _is_recent(onset_date: date | None) -> bool:
    if onset_date is None:
        return False
    return (date.today() - onset_date) <= timedelta(days=RECENT_ONSET_DAYS)


def estimate_risk_tier(
    symptoms: Iterable[str],
    onset_date: date | None,
    case_count: int,
) -> tuple[str, str]:
    """Return (tier, rationale). tier ∈ {'low','medium','high','severe'}."""
    syms, onset, cases = _normalise(symptoms, onset_date, case_count)
    recent = _is_recent(onset)

    # 1. SEVERE — textbook severe-cholera pattern
    if (
        "diarrhoea" in syms
        and "dehydration" in syms
        and recent
        and cases >= 3
    ):
        return ("severe",
                "textbook severe-cholera pattern (diarrhoea + dehydration + "
                "recent onset + multiple cases)")

    # 2. HIGH — three sub-rules, ORed
    if len(syms) >= 3:
        return ("high", "3+ symptoms reported")
    if cases >= 5 and len(syms) >= 2:
        return ("high", "outbreak-scale case count (≥5) with multiple symptoms")
    if "diarrhoea" in syms and recent:
        return ("high", "recent-onset diarrhoea")

    # 3. MEDIUM — 1 or 2 symptoms
    if 1 <= len(syms) <= 2:
        return ("medium", f"{len(syms)} non-specific symptom(s) reported")

    # 4. LOW — fallthrough
    return ("low", "no symptoms reported — request clinical assessment regardless")
```

- [ ] **Step 2: Run to verify pass**

```bash
.venv/bin/pytest tests/test_estimator.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add App/backend/estimator.py
git commit -m "Phase D: implement risk-tier estimator (cholera-pattern heuristic)"
```

### Task D.4: Wire risk-tier dropdown into the medical report form

**Files:**
- Modify: `App/backend/templates/medical_report.html`
- Modify: `App/backend/app.py`
- Create: `App/backend/tests/test_medical_form.py`

- [ ] **Step 1: Write the failing test**

Create `App/backend/tests/test_medical_form.py`:

```python
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
        row = c.execute("SELECT risk_tier FROM illness_reports ORDER BY report_id DESC LIMIT 1").fetchone()
        assert row["risk_tier"] == "high"


def test_submitting_without_risk_tier_stores_null(med_session):
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
        row = c.execute("SELECT risk_tier FROM illness_reports ORDER BY report_id DESC LIMIT 1").fetchone()
        assert row["risk_tier"] is None


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
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_medical_form.py -v
```

Expected: FAIL — no `risk_tier` field on the form.

- [ ] **Step 3: Update the form template**

Modify `App/backend/templates/medical_report.html`. Find the `<div class="field">` that contains the case_count input. Insert a new field block immediately ABOVE the symptoms field block:

```html
                <div class="field">
                    <label>Risk tier <span class="hint">(your clinical assessment, optional)</span></label>
                    <select name="risk_tier">
                        <option value="" selected>Not yet assessed — estimate on review</option>
                        <option value="low">LOW — non-specific symptoms</option>
                        <option value="medium">MEDIUM — possible waterborne illness</option>
                        <option value="high">HIGH — likely waterborne illness, clinical workup recommended</option>
                        <option value="severe">SEVERE — suspected severe cholera, urgent action</option>
                    </select>
                </div>
```

- [ ] **Step 4: Update the route handler to read + validate + persist `risk_tier`**

Modify `App/backend/app.py`. In `medical_report_submit()`, near the top with the other field reads, add:

```python
    risk_tier_raw = (request.form.get("risk_tier", "") or "").strip().lower()
```

Then add a validation block near the other validations (after `onset_date_raw` validation):

```python
    if risk_tier_raw not in ("", "low", "medium", "high", "severe"):
        return render(error="Invalid risk tier value.")
    risk_tier_value = risk_tier_raw or None
```

Then modify the `INSERT INTO illness_reports` statement to include the new column. Replace the existing INSERT in `medical_report_submit()` with:

```python
        cursor = conn.execute(
            """
            INSERT INTO illness_reports
                (station_id, reporter_phone, raw_message, parser_version,
                 report_source, submitter, case_count, onset_date, symptoms,
                 risk_tier)
            VALUES (?, NULL, ?, ?, 'medical_portal', ?, ?, ?, ?, ?)
            """,
            (
                station_id,
                raw_message,
                STATION_PARSER_VERSION,
                session.get("username"),
                case_count,
                onset_date_raw or None,
                json.dumps(symptoms_selected),
                risk_tier_value,
            ),
        )
```

- [ ] **Step 5: Run tests to verify pass**

```bash
.venv/bin/pytest tests/test_medical_form.py -v
```

Expected: all four tests PASS.

- [ ] **Step 6: Commit**

```bash
git add App/backend/templates/medical_report.html App/backend/app.py App/backend/tests/test_medical_form.py
git commit -m "Phase D: medical form takes risk_tier; persisted to illness_reports"
```

### Task D.5: GET /dashboard/reports/<id> — tests

**Files:**
- Create: `App/backend/tests/test_gov_detail_page.py`

- [ ] **Step 1: Write the failing tests**

Create `App/backend/tests/test_gov_detail_page.py`:

```python
"""Tests for /dashboard/reports/<id> — the government per-report detail page."""

import json
from datetime import date, timedelta


def _insert_report(reporter_supplied=False, source="medical_portal"):
    """Helper: insert a report directly via DB and return its id."""
    from database import connection
    with connection() as c:
        cur = c.execute(
            "INSERT INTO illness_reports "
            "(station_id, raw_message, parser_version, report_source, "
            " submitter, case_count, onset_date, symptoms, risk_tier) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                "test message",
                "test_parser_v1",
                source,
                "dr.smith" if source == "medical_portal" else None,
                3,
                date.today().isoformat(),
                json.dumps(["diarrhoea", "dehydration"]),
                "high" if reporter_supplied else None,
            ),
        )
        return cur.lastrowid


def test_anonymous_redirected_to_login(client):
    rid = _insert_report()
    r = client.get(f"/dashboard/reports/{rid}", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_medical_user_gets_403_with_link(med_session):
    rid = _insert_report()
    r = med_session.get(f"/dashboard/reports/{rid}")
    assert r.status_code == 403
    assert f"/medical/reports/{rid}".encode() in r.data


def test_gov_user_sees_report(gov_session):
    rid = _insert_report()
    r = gov_session.get(f"/dashboard/reports/{rid}")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert f"Report #{rid}" in body
    assert "diarrhoea" in body
    assert "dehydration" in body
    assert "Borehole A" in body  # station 1 name


def test_unknown_report_returns_404(gov_session):
    r = gov_session.get("/dashboard/reports/99999")
    assert r.status_code == 404


def test_reporter_supplied_tier_renders_without_estimator_banner(gov_session):
    rid = _insert_report(reporter_supplied=True)  # risk_tier='high'
    r = gov_session.get(f"/dashboard/reports/{rid}")
    body = r.data.decode("utf-8")
    assert "Reporter's clinical assessment" in body
    assert "Estimated by automated heuristic" not in body


def test_missing_tier_triggers_estimator_with_banner(gov_session):
    rid = _insert_report(reporter_supplied=False)  # risk_tier=NULL
    r = gov_session.get(f"/dashboard/reports/{rid}")
    body = r.data.decode("utf-8")
    assert "Estimated risk tier" in body
    assert "Estimated by automated heuristic" in body
    assert "not medical advice" in body.lower()
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_gov_detail_page.py -v
```

Expected: FAIL (404 — route doesn't exist).

- [ ] **Step 3: Commit (tests only)**

```bash
git add App/backend/tests/test_gov_detail_page.py
git commit -m "Phase D: tests for /dashboard/reports/<id> (red)"
```

### Task D.6: GET /dashboard/reports/<id> — implementation

**Files:**
- Create: `App/backend/templates/dashboard_report_detail.html`
- Modify: `App/backend/app.py`

- [ ] **Step 1: Create the detail page template**

Create `App/backend/templates/dashboard_report_detail.html`:

```html
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Report #{{ report['report_id'] }} — government detail</title>
    <style>
        :root {
            --bg: #0f1115; --panel: #181b22; --text: #e6e7eb;
            --muted: #8a92a3; --accent: #5ec8a8; --danger: #ff6b6b;
            --warn: #f0c674; --border: #262a33;
        }
        * { box-sizing: border-box; }
        body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
               background: var(--bg); color: var(--text); }
        header { padding: 16px 24px; border-bottom: 1px solid var(--border);
                 display: flex; align-items: baseline; justify-content: space-between; }
        header a { color: var(--accent); text-decoration: none; }
        .disclaimer { background: #2d1f15; color: var(--warn); font-size: 12px;
                      padding: 8px 24px; border-bottom: 1px solid var(--border); }
        main { max-width: 900px; margin: 0 auto; padding: 24px; }
        section { background: var(--panel); border: 1px solid var(--border);
                  border-radius: 8px; padding: 16px; margin-bottom: 16px; }
        section h2 { margin: 0 0 12px 0; font-size: 14px; font-weight: 600;
                     color: var(--muted); text-transform: uppercase;
                     letter-spacing: 0.05em; }
        dl { display: grid; grid-template-columns: 180px 1fr; gap: 8px 16px; margin: 0; font-size: 13px; }
        dt { color: var(--muted); }
        dd { margin: 0; }
        .pill { display: inline-block; padding: 4px 10px; border-radius: 12px;
                font-size: 12px; font-weight: 600; }
        .tier-low      { background: rgba(94, 200, 168, 0.15); color: var(--accent); }
        .tier-medium   { background: rgba(240, 198, 116, 0.15); color: var(--warn); }
        .tier-high     { background: rgba(255, 165, 90, 0.20); color: #ffa55a; }
        .tier-severe   { background: rgba(255, 107, 107, 0.20); color: var(--danger); }
        .tier-muted { opacity: 0.7; }
        .banner { background: rgba(240, 198, 116, 0.12); color: var(--warn);
                  padding: 10px 12px; border-radius: 6px; font-size: 13px;
                  margin-bottom: 12px; line-height: 1.4; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--border); }
        th { color: var(--muted); font-weight: 500; }
    </style>
</head>
<body>
<header>
    <h1 style="font-size: 18px; margin: 0;">
        <a href="{{ url_for('dashboard') }}">← Dashboard</a>
        &nbsp;›&nbsp; Report #{{ report['report_id'] }} · {{ report['station_name'] or 'unparsed' }}
    </h1>
    <div style="color: var(--muted); font-size: 12px;">
        Signed in as {{ session['display_name'] }}
        · <a href="{{ url_for('logout') }}">Sign out</a>
    </div>
</header>
<div class="disclaimer">
    Faecal-contamination risk + community illness signal. NOT a cholera detector.
</div>
<main>

<section>
    <h2>Report metadata</h2>
    <dl>
        <dt>Source</dt>             <dd>{{ report['report_source'] }}</dd>
        <dt>Received at</dt>        <dd>{{ report['received_at'] }}</dd>
        <dt>Submitter</dt>          <dd>{{ report['submitter'] or report['reporter_phone'] or '—' }}</dd>
        <dt>Parser version</dt>     <dd>{{ report['parser_version'] }}</dd>
    </dl>
</section>

<section>
    <h2>Structured fields</h2>
    <dl>
        <dt>Station</dt>     <dd>#{{ report['station_id'] }} {{ report['station_name'] }}</dd>
        <dt>Case count</dt>  <dd>{{ report['case_count'] or '—' }}</dd>
        <dt>Symptoms</dt>    <dd>{{ symptoms_display }}</dd>
        <dt>Onset date</dt>  <dd>{{ report['onset_date'] or '—' }}</dd>
        <dt>Notes / raw</dt> <dd><code style="font-size: 11px;">{{ report['raw_message'] }}</code></dd>
    </dl>
</section>

<section>
    <h2>Risk tier</h2>
    {% if tier_source == 'reporter' %}
        <span class="pill tier-{{ tier }}">{{ tier|upper }}</span>
        <span style="color: var(--muted); font-size: 12px; margin-left: 8px;">
            Reporter's clinical assessment
        </span>
    {% elif tier_source == 'estimated' %}
        <div class="banner">
            <strong>Estimated by automated heuristic — not medical advice.</strong>
            See rationale below. Pattern-based; clinical assessment overrides.
        </div>
        <span class="pill tier-{{ tier }} tier-muted">{{ tier|upper }}</span>
        <span style="color: var(--muted); font-size: 12px; margin-left: 8px;">
            Estimated risk tier
        </span>
        <p style="margin-top: 12px; font-size: 13px;">{{ tier_rationale }}</p>
    {% else %}
        <span style="color: var(--muted); font-size: 13px;">{{ tier_pending_text }}</span>
    {% endif %}
</section>

<section>
    <h2>Labelled readings ({{ labelled_readings|length }})</h2>
    {% if labelled_readings %}
    <table>
        <thead><tr>
            <th>Reading</th><th>Recorded at</th><th>pH</th><th>Turb (NTU)</th>
            <th>Temp (°C)</th><th>Rule</th>
        </tr></thead>
        <tbody>
            {% for lr in labelled_readings %}
            <tr>
                <td>#{{ lr['reading_id'] }}</td>
                <td>{{ lr['recorded_at'][:19] }}</td>
                <td>{{ '%.2f'|format(lr['ph']) if lr['ph'] is not none else '—' }}</td>
                <td>{{ '%.1f'|format(lr['turbidity_ntu']) if lr['turbidity_ntu'] is not none else '—' }}</td>
                <td>{{ '%.1f'|format(lr['temperature_c']) if lr['temperature_c'] is not none else '—' }}</td>
                <td style="font-size: 11px; color: var(--muted);">{{ lr['rule_description'] }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p style="color: var(--muted); font-size: 13px;">No readings labelled by this report.</p>
    {% endif %}
</section>

</main>
</body>
</html>
```

- [ ] **Step 2: Add the route to `app.py`**

Modify `App/backend/app.py`. Add the following imports near the existing imports:

```python
from datetime import date as date_cls
from flask import abort
```

Add a helper near the existing `_parse_station_id`:

```python
def _resolve_tier(report) -> dict:
    """Decide which tier to render and how. See spec §5 'Where the output is displayed'.

    Caller must pass a dict (use dict(row) for sqlite3.Row inputs)
    so .get() is available for the optional dialog_state field.
    """
    from estimator import estimate_risk_tier
    if report["risk_tier"] is not None:
        return {
            "tier_source": "reporter",
            "tier": report["risk_tier"],
            "tier_rationale": "",
            "tier_pending_text": "",
        }
    # No reporter tier — decide whether to estimate or show pending/incomplete.
    if report["report_source"] == "medical_portal":
        run_estimator = True
    else:  # sms
        run_estimator = (report.get("dialog_state") == "complete")

    if run_estimator:
        try:
            symptoms = json.loads(report["symptoms"] or "[]")
        except (json.JSONDecodeError, TypeError):
            symptoms = []
        onset = None
        if report["onset_date"]:
            try:
                onset = date_cls.fromisoformat(report["onset_date"])
            except ValueError:
                onset = None
        tier, rationale = estimate_risk_tier(
            symptoms=symptoms,
            onset_date=onset,
            case_count=report["case_count"] or 1,
        )
        return {
            "tier_source": "estimated",
            "tier": tier,
            "tier_rationale": rationale,
            "tier_pending_text": "",
        }

    # SMS, not complete
    state = report.get("dialog_state")
    if state in ("awaiting_case_count", "awaiting_symptoms", "awaiting_onset"):
        pending = "pending — awaiting reporter follow-up"
    else:
        pending = "incomplete — no structured data available"
    return {
        "tier_source": "pending",
        "tier": None,
        "tier_rationale": "",
        "tier_pending_text": pending,
    }
```

Add the route. Note: we DON'T use `@role_required("government")` here because we want a custom 403 message that points medical users at the parallel medical detail page:

```python
@app.get("/dashboard/reports/<int:report_id>")
def dashboard_report_detail(report_id: int):
    if "username" not in session:
        return redirect(url_for("login", next=request.path))
    if session.get("role") != "government":
        return (
            "This page is for government officials. "
            f"Medical staff can view this report at /medical/reports/{report_id}",
            403,
        )

    with connection() as conn:
        row = conn.execute(
            """
            SELECT ir.*, s.name AS station_name
            FROM illness_reports ir
            LEFT JOIN stations s USING (station_id)
            WHERE ir.report_id = ?
            """,
            (report_id,),
        ).fetchone()
        if row is None:
            abort(404)
        labelled_readings = conn.execute(
            """
            SELECT rl.reading_id, rl.rule_description,
                   sr.recorded_at, sr.ph, sr.turbidity_ntu, sr.temperature_c
            FROM reading_labels rl
            JOIN sensor_readings sr USING (reading_id)
            WHERE rl.report_id = ?
            ORDER BY sr.recorded_at DESC
            """,
            (report_id,),
        ).fetchall()

    tier_block = _resolve_tier(dict(row))
    try:
        symptoms_list = json.loads(row["symptoms"] or "[]")
    except (json.JSONDecodeError, TypeError):
        symptoms_list = []
    symptoms_display = ", ".join(symptoms_list) if symptoms_list else "—"

    return render_template(
        "dashboard_report_detail.html",
        report=row,
        symptoms_display=symptoms_display,
        labelled_readings=labelled_readings,
        **tier_block,
    )
```

- [ ] **Step 3: Run tests to verify pass**

```bash
.venv/bin/pytest tests/test_gov_detail_page.py -v
```

Expected: all six tests PASS.

- [ ] **Step 4: Commit**

```bash
git add App/backend/app.py App/backend/templates/dashboard_report_detail.html
git commit -m "Phase D: /dashboard/reports/<id> with estimator banner"
```

### Task D.7: Make dashboard report rows clickable + add risk-tier column

**Files:**
- Modify: `App/backend/templates/dashboard.html`
- Modify: `App/backend/app.py`
- Create: `App/backend/tests/test_dashboard_with_tier.py`

- [ ] **Step 1: Write the failing test**

Create `App/backend/tests/test_dashboard_with_tier.py`:

```python
import json
from datetime import date


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
        cur = c.execute(
            "INSERT INTO illness_reports (station_id, raw_message, parser_version, report_source) "
            "VALUES (1, 'station 1', 'v', 'sms')"
        )
        rid = cur.lastrowid
    r = gov_session.get("/dashboard")
    body = r.data.decode("utf-8")
    assert f"/dashboard/reports/{rid}" in body


def test_dashboard_shows_reporter_tier_when_set(gov_session):
    """A report row with a reporter-supplied tier shows a bright pill."""
    from database import connection
    with connection() as c:
        c.execute(
            "INSERT INTO illness_reports (station_id, raw_message, parser_version, "
            "report_source, risk_tier) "
            "VALUES (1, 't', 'v', 'medical_portal', 'severe')"
        )
    r = gov_session.get("/dashboard")
    body = r.data.decode("utf-8")
    assert "SEVERE" in body  # uppercase tier in pill
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_dashboard_with_tier.py -v
```

Expected: FAIL — no "Risk tier" column / no link / no pill.

- [ ] **Step 3: Extend the dashboard query in app.py**

Modify `App/backend/app.py`. Find the `dashboard()` view's reports query and add `risk_tier` + `report_source` + `dialog_state` to the SELECT:

```python
        reports = conn.execute(
            """
            SELECT ir.report_id, ir.station_id, s.name AS station_name,
                   ir.reporter_phone, ir.raw_message, ir.received_at,
                   ir.risk_tier, ir.report_source, ir.dialog_state,
                   ir.case_count, ir.symptoms, ir.onset_date,
                   (SELECT COUNT(*) FROM reading_labels
                     WHERE report_id = ir.report_id) AS readings_labelled
            FROM illness_reports ir
            LEFT JOIN stations s USING (station_id)
            ORDER BY ir.received_at DESC
            LIMIT 50
            """
        ).fetchall()

        # Compute the tier display for each report at render time.
        reports_with_tier = [
            {**dict(rep), "tier_block": _resolve_tier(dict(rep))}
            for rep in reports
        ]
```

Pass `reports_with_tier` (not `reports`) to the template.

- [ ] **Step 4: Update the dashboard template**

Modify `App/backend/templates/dashboard.html`. In the right panel (the `<section>` for "Recent illness reports"), replace the table header row with:

```html
                <thead>
                    <tr>
                        <th>Received</th>
                        <th>Station</th>
                        <th>Source</th>
                        <th>Risk tier</th>
                        <th>Labelled</th>
                    </tr>
                </thead>
```

Replace the row template (`{% for rep in reports %}` ... `{% endfor %}`) with:

```html
                    {% for rep in reports_with_tier %}
                    <tr style="cursor: pointer;" onclick="window.location='/dashboard/reports/{{ rep['report_id'] }}'">
                        <td>{{ rep['received_at'][:19] }}</td>
                        <td>
                            {% if rep['station_id'] %}
                                #{{ rep['station_id'] }} {{ rep['station_name'] or '—' }}
                            {% else %}
                                <span style="color: var(--danger)">unparsed</span>
                            {% endif %}
                        </td>
                        <td style="font-size: 11px; color: var(--muted);">{{ rep['report_source'] }}</td>
                        <td>
                            {% set tb = rep['tier_block'] %}
                            {% if tb['tier_source'] == 'reporter' %}
                                <span class="label-pill label-{{ tb['tier'] }}">{{ tb['tier']|upper }}</span>
                            {% elif tb['tier_source'] == 'estimated' %}
                                <span class="label-pill label-{{ tb['tier'] }}" style="opacity: 0.65;">{{ tb['tier']|upper }}</span>
                            {% else %}
                                <span style="font-size: 11px; color: var(--muted);">{{ tb['tier_pending_text'].split(' — ')[0] }}</span>
                            {% endif %}
                        </td>
                        <td class="numeric">{{ rep['readings_labelled'] }}</td>
                    </tr>
                    {% endfor %}
```

Add per-tier CSS classes at the top of the template's `<style>`, next to the existing `.label-unsafe`/`.label-clear`:

```css
        .label-low    { background: rgba(94, 200, 168, 0.18); color: var(--accent); }
        .label-medium { background: rgba(240, 198, 116, 0.20); color: #f0c674; }
        .label-high   { background: rgba(255, 165, 90, 0.20); color: #ffa55a; }
        .label-severe { background: rgba(255, 107, 107, 0.22); color: var(--danger); }
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_dashboard_with_tier.py -v
```

Expected: all three PASS.

- [ ] **Step 6: Commit**

```bash
git add App/backend/app.py App/backend/templates/dashboard.html App/backend/tests/test_dashboard_with_tier.py
git commit -m "Phase D: dashboard rows clickable + risk-tier column"
```

### Task D.8: End-to-end verification of Phase D

- [ ] **Step 1: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests PASS (smoke + migrations + estimator + medical form + gov detail + dashboard with tier).

- [ ] **Step 2: Manual smoke check (optional but recommended)**

```bash
# Wipe demo DB so this is a clean test of migrations on a from-scratch DB
rm -f data/water_safety.db data/water_safety.db-wal data/water_safety.db-shm
python app.py
```

In a browser:
1. Visit `http://localhost:5000/login`, sign in as `dr.smith` / `demo-medical-2026`.
2. File a report with risk tier = HIGH.
3. Sign out; sign in as `official.jones` / `demo-gov-2026`.
4. On the dashboard, click the new report row → detail page loads, "Reporter's clinical assessment" + HIGH pill shown, no banner.
5. File another report as `dr.smith` with NO risk tier; sign back in as gov, click the row → detail page shows estimated tier + yellow banner.

- [ ] **Step 3: Commit any small fixes from the smoke check**

If everything passes, no commit needed.

---

## Phase C — medical history page + map + medical detail page + top nav

### Task C.1: GET /medical/reports/<id> — tests

**Files:**
- Create: `App/backend/tests/test_medical_detail_page.py`

- [ ] **Step 1: Write the failing tests**

Create `App/backend/tests/test_medical_detail_page.py`:

```python
"""Tests for /medical/reports/<id> — medical-side read-only detail page."""

import json


def _insert_medical_report():
    from database import connection
    with connection() as c:
        cur = c.execute(
            "INSERT INTO illness_reports (station_id, raw_message, parser_version, "
            "report_source, submitter, case_count, symptoms, risk_tier) "
            "VALUES (1, 'test', 'v', 'medical_portal', 'dr.smith', 4, ?, 'high')",
            (json.dumps(["diarrhoea", "fever"]),),
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
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_medical_detail_page.py -v
```

Expected: FAIL (404).

### Task C.2: GET /medical/reports/<id> — implementation

**Files:**
- Create: `App/backend/templates/medical_report_detail.html`
- Modify: `App/backend/app.py`

- [ ] **Step 1: Create the medical detail template**

Create `App/backend/templates/medical_report_detail.html`:

```html
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Report #{{ report['report_id'] }} — medical detail</title>
    <style>
        :root {
            --bg: #0f1115; --panel: #181b22; --text: #e6e7eb;
            --muted: #8a92a3; --accent: #5ec8a8; --danger: #ff6b6b;
            --warn: #f0c674; --border: #262a33;
        }
        * { box-sizing: border-box; }
        body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
               background: var(--bg); color: var(--text); }
        header { padding: 16px 24px; border-bottom: 1px solid var(--border);
                 display: flex; align-items: baseline; justify-content: space-between; }
        header a { color: var(--accent); text-decoration: none; margin-right: 12px; }
        .disclaimer { background: #2d1f15; color: var(--warn); font-size: 12px;
                      padding: 8px 24px; border-bottom: 1px solid var(--border); }
        main { max-width: 760px; margin: 0 auto; padding: 24px; }
        section { background: var(--panel); border: 1px solid var(--border);
                  border-radius: 8px; padding: 16px; margin-bottom: 16px; }
        section h2 { margin: 0 0 12px 0; font-size: 14px; font-weight: 600;
                     color: var(--muted); text-transform: uppercase;
                     letter-spacing: 0.05em; }
        dl { display: grid; grid-template-columns: 180px 1fr; gap: 8px 16px; margin: 0; font-size: 13px; }
        dt { color: var(--muted); }
        dd { margin: 0; }
        .pill { display: inline-block; padding: 4px 10px; border-radius: 12px;
                font-size: 12px; font-weight: 600; }
        .tier-low      { background: rgba(94, 200, 168, 0.15); color: var(--accent); }
        .tier-medium   { background: rgba(240, 198, 116, 0.15); color: var(--warn); }
        .tier-high     { background: rgba(255, 165, 90, 0.20); color: #ffa55a; }
        .tier-severe   { background: rgba(255, 107, 107, 0.20); color: var(--danger); }
        .tier-muted { opacity: 0.7; }
    </style>
</head>
<body>
<header>
    <h1 style="font-size: 18px; margin: 0;">
        <a href="{{ url_for('medical_history') }}">← History</a>
        Report #{{ report['report_id'] }} · {{ report['station_name'] or 'unparsed' }}
    </h1>
    <div style="color: var(--muted); font-size: 12px;">
        Signed in as {{ session['display_name'] }}
        · <a href="{{ url_for('logout') }}">Sign out</a>
    </div>
</header>
<div class="disclaimer">
    Faecal-contamination risk + community illness signal. NOT a cholera detector.
</div>
<main>
<section>
    <h2>Report metadata</h2>
    <dl>
        <dt>Source</dt>      <dd>{{ report['report_source'] }}</dd>
        <dt>Received at</dt> <dd>{{ report['received_at'] }}</dd>
        <dt>Submitter</dt>   <dd>{{ report['submitter'] or '—' }}</dd>
    </dl>
</section>
<section>
    <h2>Structured fields</h2>
    <dl>
        <dt>Station</dt>     <dd>#{{ report['station_id'] }} {{ report['station_name'] }}</dd>
        <dt>Case count</dt>  <dd>{{ report['case_count'] or '—' }}</dd>
        <dt>Symptoms</dt>    <dd>{{ symptoms_display }}</dd>
        <dt>Onset date</dt>  <dd>{{ report['onset_date'] or '—' }}</dd>
    </dl>
</section>
<section>
    <h2>Risk tier</h2>
    {% if tier_source == 'reporter' %}
        <span class="pill tier-{{ tier }}">{{ tier|upper }}</span>
        <span style="color: var(--muted); font-size: 12px; margin-left: 8px;">
            Reporter's clinical assessment
        </span>
    {% elif tier_source == 'estimated' %}
        <span class="pill tier-{{ tier }} tier-muted">{{ tier|upper }}</span>
        <span style="color: var(--muted); font-size: 12px; margin-left: 8px;">
            Estimated risk tier
        </span>
    {% else %}
        <span style="color: var(--muted); font-size: 13px;">{{ tier_pending_text }}</span>
    {% endif %}
</section>
</main>
</body>
</html>
```

- [ ] **Step 2: Add the route to `app.py`**

Modify `App/backend/app.py`. Add the new route below the gov detail route:

```python
@app.get("/medical/reports/<int:report_id>")
@role_required("medical")
def medical_report_detail(report_id: int):
    with connection() as conn:
        row = conn.execute(
            """
            SELECT ir.*, s.name AS station_name
            FROM illness_reports ir
            LEFT JOIN stations s USING (station_id)
            WHERE ir.report_id = ?
            """,
            (report_id,),
        ).fetchone()
        if row is None:
            abort(404)
    tier_block = _resolve_tier(dict(row))
    try:
        symptoms_list = json.loads(row["symptoms"] or "[]")
    except (json.JSONDecodeError, TypeError):
        symptoms_list = []
    symptoms_display = ", ".join(symptoms_list) if symptoms_list else "—"
    return render_template(
        "medical_report_detail.html",
        report=row,
        symptoms_display=symptoms_display,
        **tier_block,
    )
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/test_medical_detail_page.py -v
```

Expected: all 5 PASS. (`test_medical_user_sees_report` will also need the medical_history route to exist for the `← History` link's `url_for` to resolve — if it errors with a BuildError, add a placeholder route now and finish in Task C.4. Quick stub: `@app.get("/medical/history") @role_required("medical") def medical_history(): return "history coming"`. Replace in Task C.4.)

- [ ] **Step 4: Commit**

```bash
git add App/backend/app.py App/backend/templates/medical_report_detail.html App/backend/tests/test_medical_detail_page.py
git commit -m "Phase C: /medical/reports/<id> read-only detail page"
```

### Task C.3: GET /medical/history — tests

**Files:**
- Create: `App/backend/tests/test_medical_history.py`

- [ ] **Step 1: Write the failing tests**

Create `App/backend/tests/test_medical_history.py`:

```python
"""Tests for /medical/history."""

import json
import re


def _insert_medical_reports(n=3):
    from database import connection
    with connection() as c:
        for i in range(n):
            c.execute(
                "INSERT INTO illness_reports (station_id, raw_message, parser_version, "
                "report_source, submitter, case_count, symptoms, risk_tier) "
                "VALUES (?, ?, ?, 'medical_portal', 'dr.smith', ?, ?, ?)",
                (
                    (i % 4) + 1,  # rotate stations 1..4
                    f"report {i}",
                    "v",
                    i + 1,
                    json.dumps(["diarrhoea"]),
                    ["low", "medium", "high"][i % 3],
                ),
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
    # Two reports inserted; submitter shown
    assert body.count("dr.smith") >= 2


def test_history_excludes_sms_reports(med_session):
    """SMS reports should NOT appear in the medical history."""
    from database import connection
    _insert_medical_reports(1)
    with connection() as c:
        c.execute(
            "INSERT INTO illness_reports (station_id, raw_message, parser_version, "
            "report_source, reporter_phone) "
            "VALUES (1, 'station 1', 'v', 'sms', '+1555')"
        )
    r = med_session.get("/medical/history")
    body = r.data.decode("utf-8")
    assert "+1555" not in body
    assert "1555" not in body


def test_history_includes_leaflet_map(med_session):
    r = med_session.get("/medical/history")
    body = r.data.decode("utf-8")
    assert "leaflet" in body.lower()
    # Harare centring
    assert "-17.82" in body or "-17.83" in body
    assert "31.05" in body
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_medical_history.py -v
```

Expected: FAIL (either 404 if no stub, or template missing).

### Task C.4: GET /medical/history — implementation

**Files:**
- Create: `App/backend/templates/medical_history.html`
- Modify: `App/backend/app.py`

- [ ] **Step 1: Create the history template with map**

Create `App/backend/templates/medical_history.html`:

```html
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>History — medical portal</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
          crossorigin=""/>
    <style>
        :root {
            --bg: #0f1115; --panel: #181b22; --text: #e6e7eb;
            --muted: #8a92a3; --accent: #5ec8a8; --danger: #ff6b6b;
            --warn: #f0c674; --border: #262a33;
        }
        * { box-sizing: border-box; }
        body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
               background: var(--bg); color: var(--text); }
        header { padding: 16px 24px; border-bottom: 1px solid var(--border);
                 display: flex; align-items: baseline; justify-content: space-between; }
        header a { color: var(--accent); text-decoration: none; margin-right: 12px; }
        .disclaimer { background: #2d1f15; color: var(--warn); font-size: 12px;
                      padding: 8px 24px; border-bottom: 1px solid var(--border); }
        main { max-width: 1100px; margin: 0 auto; padding: 24px; }
        #map { height: 300px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 24px; }
        section { background: var(--panel); border: 1px solid var(--border);
                  border-radius: 8px; padding: 16px; }
        section h2 { margin: 0 0 12px 0; font-size: 14px; font-weight: 600;
                     color: var(--muted); text-transform: uppercase;
                     letter-spacing: 0.05em; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--border); }
        th { color: var(--muted); font-weight: 500; }
        tr.row-link { cursor: pointer; }
        tr.row-link:hover { background: rgba(255,255,255,0.03); }
        .pill { display: inline-block; padding: 2px 8px; border-radius: 10px;
                font-size: 11px; font-weight: 600; }
        .tier-low { background: rgba(94, 200, 168, 0.18); color: var(--accent); }
        .tier-medium { background: rgba(240, 198, 116, 0.20); color: #f0c674; }
        .tier-high { background: rgba(255, 165, 90, 0.20); color: #ffa55a; }
        .tier-severe { background: rgba(255, 107, 107, 0.22); color: var(--danger); }
        .tier-muted { opacity: 0.65; }
    </style>
</head>
<body>
<header>
    <h1 style="font-size: 18px; margin: 0;">
        <a href="{{ url_for('medical_report_form') }}">File a report</a>
        <a href="{{ url_for('medical_history') }}">History</a>
    </h1>
    <div style="color: var(--muted); font-size: 12px;">
        Signed in as {{ session['display_name'] }}
        · <a href="{{ url_for('logout') }}">Sign out</a>
    </div>
</header>
<div class="disclaimer">
    Faecal-contamination risk + community illness signal. NOT a cholera detector.
</div>
<main>
    <div id="map"></div>
    <section>
        <h2>Reports filed via medical portal ({{ reports|length }})</h2>
        {% if reports %}
        <table>
            <thead><tr>
                <th>Submitted</th><th>Submitter</th><th>Station</th>
                <th>Cases</th><th>Symptoms</th><th>Risk tier</th><th>Onset</th>
            </tr></thead>
            <tbody>
                {% for rep in reports %}
                <tr class="row-link" onclick="window.location='/medical/reports/{{ rep['report_id'] }}'">
                    <td>{{ rep['received_at'][:19] }}</td>
                    <td>{{ rep['submitter'] }}</td>
                    <td>#{{ rep['station_id'] }} {{ rep['station_name'] }}</td>
                    <td>{{ rep['case_count'] or '—' }}</td>
                    <td>{{ rep['symptoms_display'] }}</td>
                    <td>
                        {% if rep['tier_source'] == 'reporter' %}
                            <span class="pill tier-{{ rep['tier'] }}">{{ rep['tier']|upper }}</span>
                        {% elif rep['tier_source'] == 'estimated' %}
                            <span class="pill tier-{{ rep['tier'] }} tier-muted">{{ rep['tier']|upper }}</span>
                        {% else %}
                            <span style="color: var(--muted); font-size: 11px;">—</span>
                        {% endif %}
                    </td>
                    <td>{{ rep['onset_date'] or '—' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p style="color: var(--muted);">No medical-portal reports yet. File one via "File a report" above.</p>
        {% endif %}
    </section>
</main>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
        crossorigin=""></script>
<script>
    const HARARE = [-17.8292, 31.0522];
    const map = L.map('map').setView(HARARE, 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    const stations = {{ stations_json|safe }};
    stations.forEach(s => {
        const radius = 6 + Math.min(s.report_count, 10) * 2;
        const color = s.report_count > 0 ? '#5ec8a8' : '#6a7383';
        L.circleMarker([s.latitude, s.longitude], {
            radius: radius,
            fillColor: color,
            color: color,
            fillOpacity: s.report_count > 0 ? 0.6 : 0.25,
            weight: 1,
        }).addTo(map).bindPopup(
            `<strong>${s.name}</strong><br>` +
            `${s.report_count} medical-portal report(s)` +
            (s.last_report ? `<br>Last: ${s.last_report.slice(0, 19)}` : '')
        );
    });
</script>
</body>
</html>
```

- [ ] **Step 2: Add the history route to `app.py`**

Modify `App/backend/app.py`. If a stub was added in Task C.2, replace it. Otherwise add:

```python
@app.get("/medical/history")
@role_required("medical")
def medical_history():
    with connection() as conn:
        report_rows = conn.execute(
            """
            SELECT ir.*, s.name AS station_name
            FROM illness_reports ir
            LEFT JOIN stations s USING (station_id)
            WHERE ir.report_source = 'medical_portal'
            ORDER BY ir.received_at DESC
            LIMIT 50
            """,
        ).fetchall()
        stations = conn.execute(
            """
            SELECT s.station_id, s.name, s.latitude, s.longitude,
                   (SELECT COUNT(*) FROM illness_reports
                      WHERE station_id = s.station_id
                        AND report_source = 'medical_portal') AS report_count,
                   (SELECT MAX(received_at) FROM illness_reports
                      WHERE station_id = s.station_id
                        AND report_source = 'medical_portal') AS last_report
            FROM stations s
            ORDER BY s.station_id
            """,
        ).fetchall()

    reports_view = []
    for rep in report_rows:
        tier_block = _resolve_tier(dict(rep))
        try:
            symptoms_list = json.loads(rep["symptoms"] or "[]")
        except (json.JSONDecodeError, TypeError):
            symptoms_list = []
        reports_view.append({
            **dict(rep),
            **tier_block,
            "symptoms_display": ", ".join(symptoms_list) if symptoms_list else "—",
        })

    stations_json = json.dumps([dict(s) for s in stations])
    return render_template(
        "medical_history.html",
        reports=reports_view,
        stations_json=stations_json,
    )
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/test_medical_history.py -v
```

Expected: all 6 PASS.

- [ ] **Step 4: Commit**

```bash
git add App/backend/app.py App/backend/templates/medical_history.html App/backend/tests/test_medical_history.py
git commit -m "Phase C: /medical/history with Harare-centred Leaflet map"
```

### Task C.5: Top-nav links on `/medical/report`

**Files:**
- Modify: `App/backend/templates/medical_report.html`

- [ ] **Step 1: Add nav links to the medical-report header**

Modify `App/backend/templates/medical_report.html`. Replace the `<header>` block with:

```html
    <header>
        <h1 style="font-size: 18px; margin: 0;">
            <a href="{{ url_for('medical_report_form') }}" style="color: var(--accent); text-decoration: none; margin-right: 12px;">File a report</a>
            <a href="{{ url_for('medical_history') }}" style="color: var(--accent); text-decoration: none; margin-right: 12px;">History</a>
        </h1>
        <div class="meta">
            Signed in as {{ session['display_name'] }} ({{ session['role'] }})
            <a href="{{ url_for('logout') }}">Sign out</a>
        </div>
    </header>
```

- [ ] **Step 2: Quick render check via the existing test**

```bash
.venv/bin/pytest tests/test_medical_form.py -v
```

Expected: still all PASS (no change in form behaviour).

- [ ] **Step 3: Commit**

```bash
git add App/backend/templates/medical_report.html
git commit -m "Phase C: top-nav links on /medical/report"
```

### Task C.6: End-to-end verification of Phase C

- [ ] **Step 1: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Manual smoke check**

In a browser:
1. Sign in as `dr.smith`.
2. Top of `/medical/report` shows "File a report" + "History" links.
3. Click "History" → map renders centred on Harare, table shows reports filed so far.
4. Click any report row → `/medical/reports/<id>` loads, shows fields + risk tier (no banner, no actions).
5. Sign out, sign in as `official.jones`. Try `http://localhost:5000/medical/history` directly → 403.

---

## Phase E — action buttons + interventions table

### Task E.1: Schema migration — `stations.is_closed` + `interventions` table

**Files:**
- Modify: `App/backend/database.py`
- Modify: `App/backend/tests/test_migrations.py`

- [ ] **Step 1: Write the failing tests**

Append to `App/backend/tests/test_migrations.py`:

```python
def test_stations_has_is_closed_column(app):
    from database import connection
    with connection() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(stations)").fetchall()}
        assert "is_closed" in cols
        row = c.execute("SELECT is_closed FROM stations WHERE station_id = 1").fetchone()
        assert row["is_closed"] == 0  # default


def test_interventions_table_exists_and_constrains_action(app):
    from database import connection
    import sqlite3
    with connection() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(interventions)").fetchall()}
        assert {"station_id", "action_type", "triggered_by",
                "triggered_at", "related_report_id", "notes"}.issubset(cols)
        c.execute(
            "INSERT INTO interventions (station_id, action_type, triggered_by) "
            "VALUES (1, 'close_borehole', 'official.jones')"
        )
        try:
            c.execute(
                "INSERT INTO interventions (station_id, action_type, triggered_by) "
                "VALUES (1, 'bogus_action', 'x')"
            )
            assert False, "CHECK should have rejected bogus action_type"
        except sqlite3.IntegrityError:
            pass
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_migrations.py -v
```

Expected: FAIL on the two new tests.

- [ ] **Step 3: Add the migration**

Modify `App/backend/database.py`. Append to the `SCHEMA` string (after the `reading_labels` block, before the closing triple-quote):

```sql

CREATE TABLE IF NOT EXISTS interventions (
    intervention_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id         INTEGER NOT NULL REFERENCES stations(station_id),
    action_type        TEXT    NOT NULL
        CHECK (action_type IN (
            'close_borehole', 'reopen_borehole',
            'dispatch_sample_team', 'dispatch_medical_team')),
    triggered_by       TEXT    NOT NULL,
    triggered_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    related_report_id  INTEGER REFERENCES illness_reports(report_id),
    notes              TEXT
);

CREATE INDEX IF NOT EXISTS idx_interventions_station_time
    ON interventions(station_id, triggered_at);
CREATE INDEX IF NOT EXISTS idx_interventions_report
    ON interventions(related_report_id);
```

Then add a new `_migrate_stations(conn)` helper to apply `is_closed` to existing DBs. Replace the body of `_migrate(conn)` with:

```python
def _migrate(conn: sqlite3.Connection) -> None:
    existing_reports = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(illness_reports)").fetchall()
    }
    added_reports_columns = [
        ("report_source", "TEXT NOT NULL DEFAULT 'sms'"),
        ("submitter",     "TEXT"),
        ("case_count",    "INTEGER"),
        ("onset_date",    "TEXT"),
        ("symptoms",      "TEXT"),
        ("risk_tier",     "TEXT CHECK (risk_tier IN ('low','medium','high','severe'))"),
    ]
    for col_name, col_type in added_reports_columns:
        if col_name not in existing_reports:
            conn.execute(
                f"ALTER TABLE illness_reports ADD COLUMN {col_name} {col_type}"
            )

    existing_stations = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(stations)").fetchall()
    }
    if "is_closed" not in existing_stations:
        conn.execute("ALTER TABLE stations ADD COLUMN is_closed INTEGER NOT NULL DEFAULT 0")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_migrations.py -v
```

Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add App/backend/database.py App/backend/tests/test_migrations.py
git commit -m "Phase E: stations.is_closed + interventions table"
```

### Task E.2: POST /actions — tests

**Files:**
- Create: `App/backend/tests/test_actions.py`

- [ ] **Step 1: Write the failing tests**

Create `App/backend/tests/test_actions.py`:

```python
"""Tests for POST /actions."""


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
        row = c.execute("SELECT is_closed FROM stations WHERE station_id = 1").fetchone()
        assert row["is_closed"] == 1
        iv = c.execute(
            "SELECT action_type, triggered_by FROM interventions ORDER BY intervention_id DESC LIMIT 1"
        ).fetchone()
        assert iv["action_type"] == "close_borehole"
        assert iv["triggered_by"] == "official.jones"


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
        row = c.execute("SELECT is_closed FROM stations WHERE station_id = 1").fetchone()
        assert row["is_closed"] == 0


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
            "SELECT action_type, notes FROM interventions ORDER BY intervention_id DESC LIMIT 1"
        ).fetchone()
        assert iv["action_type"] == "dispatch_sample_team"
        assert iv["notes"] == "send the team"


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
        cur = c.execute(
            "INSERT INTO illness_reports (station_id, raw_message, parser_version, report_source) "
            "VALUES (1, 'r', 'v', 'sms')"
        )
        rid = cur.lastrowid
    gov_session.post("/actions", data={
        "action_type": "dispatch_medical_team",
        "station_id": "1",
        "related_report_id": str(rid),
    })
    with connection() as c:
        iv = c.execute(
            "SELECT related_report_id FROM interventions ORDER BY intervention_id DESC LIMIT 1"
        ).fetchone()
        assert iv["related_report_id"] == rid


def test_notes_truncated_to_500(gov_session):
    long_note = "x" * 1000
    gov_session.post("/actions", data={
        "action_type": "dispatch_sample_team",
        "station_id": "1",
        "notes": long_note,
    })
    from database import connection
    with connection() as c:
        iv = c.execute("SELECT notes FROM interventions ORDER BY intervention_id DESC LIMIT 1").fetchone()
        assert len(iv["notes"]) == 500
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_actions.py -v
```

Expected: FAIL (404 — route doesn't exist).

### Task E.3: POST /actions — implementation

**Files:**
- Modify: `App/backend/app.py`

- [ ] **Step 1: Add the actions endpoint**

Modify `App/backend/app.py`. Add this constant near `SYMPTOMS`:

```python
ACTION_TYPES = {
    "close_borehole",
    "reopen_borehole",
    "dispatch_sample_team",
    "dispatch_medical_team",
}
```

Add the route handler:

```python
@app.post("/actions")
@role_required("government")
def post_action():
    action_type = (request.form.get("action_type", "") or "").strip()
    station_raw = (request.form.get("station_id", "") or "").strip()
    related_raw = (request.form.get("related_report_id", "") or "").strip()
    notes = (request.form.get("notes", "") or "").strip()[:500] or None

    if action_type not in ACTION_TYPES:
        return ("invalid action_type", 400)

    try:
        station_id = int(station_raw)
    except (TypeError, ValueError):
        return ("invalid station_id", 400)

    related_id = None
    if related_raw:
        try:
            related_id = int(related_raw)
        except (TypeError, ValueError):
            return ("invalid related_report_id", 400)

    with connection() as conn:
        station = conn.execute(
            "SELECT is_closed FROM stations WHERE station_id = ?", (station_id,)
        ).fetchone()
        if station is None:
            return (f"unknown station_id {station_id}", 400)

        if action_type == "close_borehole" and station["is_closed"]:
            return (f"station {station_id} is already closed", 400)
        if action_type == "reopen_borehole" and not station["is_closed"]:
            return (f"station {station_id} is already open", 400)

        conn.execute(
            """
            INSERT INTO interventions
                (station_id, action_type, triggered_by, related_report_id, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (station_id, action_type, session["username"], related_id, notes),
        )
        if action_type == "close_borehole":
            conn.execute("UPDATE stations SET is_closed = 1 WHERE station_id = ?", (station_id,))
        elif action_type == "reopen_borehole":
            conn.execute("UPDATE stations SET is_closed = 0 WHERE station_id = ?", (station_id,))

    referrer = request.referrer or ""
    if referrer.startswith("/") or referrer.startswith(request.host_url):
        return redirect(referrer)
    return redirect(url_for("dashboard"))
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/test_actions.py -v
```

Expected: all 11 PASS.

- [ ] **Step 3: Commit**

```bash
git add App/backend/app.py App/backend/tests/test_actions.py
git commit -m "Phase E: POST /actions for close/reopen/dispatch"
```

### Task E.4: Render action buttons on the dashboard + lock badge

**Files:**
- Modify: `App/backend/app.py`
- Modify: `App/backend/templates/dashboard.html`
- Create: `App/backend/tests/test_dashboard_actions.py`

- [ ] **Step 1: Write the failing test**

Create `App/backend/tests/test_dashboard_actions.py`:

```python
def test_dashboard_has_action_buttons_per_station(gov_session):
    r = gov_session.get("/dashboard")
    body = r.data.decode("utf-8")
    # Three action types should each appear at least once
    assert "close_borehole" in body
    assert "dispatch_sample_team" in body
    assert "dispatch_medical_team" in body


def test_dashboard_shows_lock_badge_for_closed_station(gov_session):
    gov_session.post("/actions", data={"action_type": "close_borehole", "station_id": "1"})
    r = gov_session.get("/dashboard")
    body = r.data.decode("utf-8")
    # The closed station should show the lock prefix (\U0001F512 is 🔒)
    assert "\U0001F512" in body or "lock" in body.lower()


def test_closed_station_shows_reopen_not_close(gov_session):
    gov_session.post("/actions", data={"action_type": "close_borehole", "station_id": "1"})
    r = gov_session.get("/dashboard")
    body = r.data.decode("utf-8")
    # The button for station 1 should now say Reopen, not Close
    # (We can't easily test per-row, but at least Reopen must appear)
    assert "reopen_borehole" in body
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_dashboard_actions.py -v
```

Expected: FAIL.

- [ ] **Step 3: Extend the dashboard query for is_closed**

Modify `App/backend/app.py`. In `dashboard()`, change the stations query to include `is_closed`:

```python
        stations = conn.execute(
            """
            WITH latest AS (
                SELECT station_id, MAX(recorded_at) AS latest_at
                FROM sensor_readings
                GROUP BY station_id
            )
            SELECT s.station_id,
                   s.name,
                   s.is_closed,
                   r.recorded_at,
                   r.ph,
                   r.turbidity_ntu,
                   r.temperature_c,
                   r.rainfall_mm,
                   EXISTS (
                       SELECT 1 FROM illness_reports ir
                       WHERE ir.station_id = s.station_id
                         AND ir.received_at >= ?
                   ) AS is_unsafe
            FROM stations s
            LEFT JOIN latest l USING (station_id)
            LEFT JOIN sensor_readings r
                ON r.station_id = s.station_id
               AND r.recorded_at = l.latest_at
            ORDER BY s.station_id
            """,
            (status_cutoff,),
        ).fetchall()
```

- [ ] **Step 4: Update the dashboard template**

Modify `App/backend/templates/dashboard.html`. In the left-panel table (`Station status`), update the row template to add a lock prefix and an action area. Find the `{% for s in stations %}` block and replace it with:

```html
                    {% for s in stations %}
                    <tr {% if s['is_closed'] %}style="opacity: 0.7;"{% endif %}>
                        <td>
                            {% if s['is_closed'] %}🔒 {% endif %}#{{ s['station_id'] }} {{ s['name'] }}
                        </td>
                        <td>{{ s['recorded_at'][:19] if s['recorded_at'] else 'no readings yet' }}</td>
                        <td class="numeric">{{ '%.2f'|format(s['ph']) if s['ph'] is not none else '—' }}</td>
                        <td class="numeric">{{ '%.1f'|format(s['turbidity_ntu']) if s['turbidity_ntu'] is not none else '—' }}</td>
                        <td class="numeric">{{ '%.1f'|format(s['temperature_c']) if s['temperature_c'] is not none else '—' }}</td>
                        <td class="numeric">{{ '%.1f'|format(s['rainfall_mm']) if s['rainfall_mm'] is not none else '—' }}</td>
                        <td>
                            {% if s['is_unsafe'] %}
                                <span class="label-pill label-unsafe">unsafe</span>
                            {% else %}
                                <span class="label-pill label-clear">clear</span>
                            {% endif %}
                        </td>
                        <td style="white-space: nowrap;">
                            {% if s['is_closed'] %}
                                <form method="POST" action="{{ url_for('post_action') }}" style="display: inline;"
                                      onsubmit="return confirm('Reopen station {{ s['station_id'] }}?');">
                                    <input type="hidden" name="action_type" value="reopen_borehole">
                                    <input type="hidden" name="station_id" value="{{ s['station_id'] }}">
                                    <button type="submit" class="btn-action">Reopen</button>
                                </form>
                            {% else %}
                                <form method="POST" action="{{ url_for('post_action') }}" style="display: inline;"
                                      onsubmit="return confirm('Close station {{ s['station_id'] }}?');">
                                    <input type="hidden" name="action_type" value="close_borehole">
                                    <input type="hidden" name="station_id" value="{{ s['station_id'] }}">
                                    <button type="submit" class="btn-action">Close</button>
                                </form>
                            {% endif %}
                            <form method="POST" action="{{ url_for('post_action') }}" style="display: inline;"
                                  onsubmit="return confirm('Dispatch sample team to station {{ s['station_id'] }}?');">
                                <input type="hidden" name="action_type" value="dispatch_sample_team">
                                <input type="hidden" name="station_id" value="{{ s['station_id'] }}">
                                <button type="submit" class="btn-action">Sample</button>
                            </form>
                            <form method="POST" action="{{ url_for('post_action') }}" style="display: inline;"
                                  onsubmit="return confirm('Dispatch medical team to station {{ s['station_id'] }}?');">
                                <input type="hidden" name="action_type" value="dispatch_medical_team">
                                <input type="hidden" name="station_id" value="{{ s['station_id'] }}">
                                <button type="submit" class="btn-action">Medical</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
```

Add an "Actions" column header right after "Status" in the `<thead>`:

```html
                        <th>Status</th>
                        <th>Actions</th>
```

Add the button styling in the `<style>` block:

```css
        .btn-action {
            padding: 4px 8px; font-size: 11px; font-weight: 600;
            background: var(--input-bg, #11141a); color: var(--text);
            border: 1px solid var(--border); border-radius: 4px;
            cursor: pointer; margin-right: 4px;
        }
        .btn-action:hover { background: var(--accent); color: #0f1115; }
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_dashboard_actions.py -v
```

Expected: all 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add App/backend/app.py App/backend/templates/dashboard.html App/backend/tests/test_dashboard_actions.py
git commit -m "Phase E: dashboard action buttons + lock badge for closed stations"
```

### Task E.5: Action buttons + interventions log on report detail page

**Files:**
- Modify: `App/backend/app.py`
- Modify: `App/backend/templates/dashboard_report_detail.html`
- Create: `App/backend/tests/test_detail_actions.py`

- [ ] **Step 1: Write the failing test**

Create `App/backend/tests/test_detail_actions.py`:

```python
def _insert_report(station_id=1):
    from database import connection
    with connection() as c:
        cur = c.execute(
            "INSERT INTO illness_reports (station_id, raw_message, parser_version, report_source) "
            "VALUES (?, 'station x', 'v', 'sms')",
            (station_id,),
        )
        return cur.lastrowid


def test_detail_page_has_action_buttons(gov_session):
    rid = _insert_report()
    r = gov_session.get(f"/dashboard/reports/{rid}")
    body = r.data.decode("utf-8")
    assert "close_borehole" in body
    assert "dispatch_sample_team" in body
    assert "dispatch_medical_team" in body
    assert str(rid) in body  # related_report_id hidden field


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
            "SELECT related_report_id FROM interventions ORDER BY intervention_id DESC LIMIT 1"
        ).fetchone()
        assert iv["related_report_id"] == rid


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
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_detail_actions.py -v
```

Expected: FAIL (no buttons, no interventions log on detail page).

- [ ] **Step 3: Extend the detail-page view to fetch interventions**

Modify `App/backend/app.py`. In `dashboard_report_detail()`, after the labelled_readings query, add:

```python
        interventions = conn.execute(
            """
            SELECT intervention_id, action_type, triggered_by, triggered_at, notes
            FROM interventions
            WHERE related_report_id = ?
            ORDER BY triggered_at ASC
            """,
            (report_id,),
        ).fetchall()
```

Pass `interventions=interventions` into `render_template`.

- [ ] **Step 4: Update the detail template**

Modify `App/backend/templates/dashboard_report_detail.html`. Add two new `<section>` blocks at the bottom of `<main>` (before `</main>`):

```html
<section>
    <h2>Actions</h2>
    <form method="POST" action="{{ url_for('post_action') }}" style="display: inline;"
          onsubmit="return confirm('Close station {{ report['station_id'] }}?');">
        <input type="hidden" name="action_type" value="close_borehole">
        <input type="hidden" name="station_id" value="{{ report['station_id'] }}">
        <input type="hidden" name="related_report_id" value="{{ report['report_id'] }}">
        <button type="submit">Close borehole</button>
    </form>
    <form method="POST" action="{{ url_for('post_action') }}" style="display: inline;"
          onsubmit="return confirm('Dispatch sample team?');">
        <input type="hidden" name="action_type" value="dispatch_sample_team">
        <input type="hidden" name="station_id" value="{{ report['station_id'] }}">
        <input type="hidden" name="related_report_id" value="{{ report['report_id'] }}">
        <button type="submit">Send sample team</button>
    </form>
    <form method="POST" action="{{ url_for('post_action') }}" style="display: inline;"
          onsubmit="return confirm('Dispatch medical team?');">
        <input type="hidden" name="action_type" value="dispatch_medical_team">
        <input type="hidden" name="station_id" value="{{ report['station_id'] }}">
        <input type="hidden" name="related_report_id" value="{{ report['report_id'] }}">
        <button type="submit">Send medical team</button>
    </form>
</section>

<section>
    <h2>Interventions linked to this report ({{ interventions|length }})</h2>
    {% if interventions %}
    <table>
        <thead><tr>
            <th>When</th><th>Action</th><th>Triggered by</th><th>Notes</th>
        </tr></thead>
        <tbody>
            {% for iv in interventions %}
            <tr>
                <td>{{ iv['triggered_at'][:19] }}</td>
                <td><code>{{ iv['action_type'] }}</code></td>
                <td>{{ iv['triggered_by'] }}</td>
                <td>{{ iv['notes'] or '—' }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p style="color: var(--muted); font-size: 13px;">No interventions yet.</p>
    {% endif %}
</section>
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_detail_actions.py -v
```

Expected: all 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add App/backend/app.py App/backend/templates/dashboard_report_detail.html App/backend/tests/test_detail_actions.py
git commit -m "Phase E: action buttons + interventions log on report detail"
```

### Task E.6: End-to-end verification of Phase E

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Manual smoke check**

1. Sign in as gov. Click "Close" on station 1 → confirm → page reloads with 🔒 and "Reopen" button.
2. Click "Reopen" → confirm → page reloads with "Close" button restored.
3. Click on a report row → detail page. Click "Send sample team" with notes → confirm → page reloads with a row in the Interventions section.

---

## Phase F — SMS multi-turn dialog

### Task F.1: Schema migration — `dialog_state`

**Files:**
- Modify: `App/backend/database.py`
- Modify: `App/backend/tests/test_migrations.py`

- [ ] **Step 1: Write the failing test**

Append to `App/backend/tests/test_migrations.py`:

```python
def test_illness_reports_has_dialog_state_column(app):
    from database import connection
    import sqlite3
    with connection() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(illness_reports)").fetchall()}
        assert "dialog_state" in cols

        valid = ["awaiting_case_count", "awaiting_symptoms", "awaiting_onset",
                 "complete", "abandoned"]
        for s in valid:
            c.execute(
                "INSERT INTO illness_reports (raw_message, parser_version, dialog_state) "
                "VALUES (?, 'v', ?)", ("t", s)
            )
        try:
            c.execute(
                "INSERT INTO illness_reports (raw_message, parser_version, dialog_state) "
                "VALUES ('t', 'v', 'bogus')"
            )
            assert False, "CHECK should reject bogus state"
        except sqlite3.IntegrityError:
            pass
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_migrations.py::test_illness_reports_has_dialog_state_column -v
```

Expected: FAIL.

- [ ] **Step 3: Add the migration**

Modify `App/backend/database.py`. Extend `added_reports_columns` in `_migrate()`:

```python
    added_reports_columns = [
        ("report_source", "TEXT NOT NULL DEFAULT 'sms'"),
        ("submitter",     "TEXT"),
        ("case_count",    "INTEGER"),
        ("onset_date",    "TEXT"),
        ("symptoms",      "TEXT"),
        ("risk_tier",     "TEXT CHECK (risk_tier IN ('low','medium','high','severe'))"),
        ("dialog_state",  "TEXT CHECK (dialog_state IN ('awaiting_case_count','awaiting_symptoms','awaiting_onset','complete','abandoned'))"),
    ]
```

Also update the SCHEMA's `CREATE TABLE illness_reports` block to add `dialog_state TEXT CHECK (...)` so fresh DBs include it.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_migrations.py -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add App/backend/database.py App/backend/tests/test_migrations.py
git commit -m "Phase F: dialog_state column on illness_reports"
```

### Task F.2: SMS dialog parsers — tests

**Files:**
- Create: `App/backend/tests/test_sms_parsers.py`

- [ ] **Step 1: Write the failing tests**

Create `App/backend/tests/test_sms_parsers.py`:

```python
"""Tests for the SMS state-machine parsers (parse_case_count, parse_symptoms, parse_onset)."""

from datetime import date


def test_parse_case_count_accepts_positive_integers():
    from sms_dialog import parse_case_count
    assert parse_case_count("3") == 3
    assert parse_case_count("17") == 17


def test_parse_case_count_rejects_zero_and_negative():
    from sms_dialog import parse_case_count
    assert parse_case_count("0") is None
    assert parse_case_count("-2") is None


def test_parse_case_count_rejects_above_200():
    from sms_dialog import parse_case_count
    assert parse_case_count("500") is None


def test_parse_case_count_extracts_from_text():
    from sms_dialog import parse_case_count
    assert parse_case_count("about 5 people") == 5


def test_parse_case_count_rejects_garbage():
    from sms_dialog import parse_case_count
    assert parse_case_count("nope") is None


def test_parse_symptoms_by_digit():
    from sms_dialog import parse_symptoms
    assert parse_symptoms("1,3") == ["diarrhoea", "fever"]
    assert parse_symptoms("1 2 3 4") == ["diarrhoea", "vomiting", "fever", "dehydration"]


def test_parse_symptoms_by_name():
    from sms_dialog import parse_symptoms
    assert parse_symptoms("diarrhoea, fever") == ["diarrhoea", "fever"]


def test_parse_symptoms_dedupes():
    from sms_dialog import parse_symptoms
    assert parse_symptoms("1,1,1") == ["diarrhoea"]


def test_parse_symptoms_returns_none_on_no_matches():
    from sms_dialog import parse_symptoms
    assert parse_symptoms("nothing") is None
    assert parse_symptoms("") is None


def test_parse_onset_today():
    from sms_dialog import parse_onset
    assert parse_onset("today") == date.today()
    assert parse_onset("TODAY") == date.today()


def test_parse_onset_yesterday():
    from sms_dialog import parse_onset
    from datetime import timedelta
    assert parse_onset("yesterday") == date.today() - timedelta(days=1)


def test_parse_onset_dd_mm():
    from sms_dialog import parse_onset
    today = date.today()
    parsed = parse_onset(f"{today.day:02d}/{today.month:02d}")
    assert parsed == today


def test_parse_onset_rejects_future():
    from sms_dialog import parse_onset
    from datetime import timedelta
    future = date.today() + timedelta(days=10)
    assert parse_onset(f"{future.day:02d}/{future.month:02d}") is None


def test_parse_onset_rejects_garbage():
    from sms_dialog import parse_onset
    assert parse_onset("sometime") is None
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_sms_parsers.py -v
```

Expected: FAIL on import (`No module named 'sms_dialog'`).

### Task F.3: SMS dialog parsers — implementation

**Files:**
- Create: `App/backend/sms_dialog.py`

- [ ] **Step 1: Implement the parsers**

Create `App/backend/sms_dialog.py`:

```python
"""Multi-turn SMS dialog parsers + state-machine helpers.

Spec: docs/superpowers/specs/2026-05-28-medical-gov-portal-design.md §8.

Pure parse functions return parsed values or None (re-prompt signal).
The state-machine step function is consumed by app.py's /sms route.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Iterable

SYMPTOM_BY_DIGIT = {
    "1": "diarrhoea",
    "2": "vomiting",
    "3": "fever",
    "4": "dehydration",
}
SYMPTOM_NAMES = set(SYMPTOM_BY_DIGIT.values())

INTEGER_RE = re.compile(r"-?\d+")
DDMM_RE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$")


def parse_case_count(message: str) -> int | None:
    if not message:
        return None
    m = INTEGER_RE.search(message)
    if not m:
        return None
    try:
        n = int(m.group(0))
    except ValueError:
        return None
    if n < 1 or n > 200:
        return None
    return n


def parse_symptoms(message: str) -> list[str] | None:
    if not message:
        return None
    tokens = re.split(r"[\s,;]+", message.lower())
    seen: list[str] = []
    for token in tokens:
        token = token.strip()
        if token in SYMPTOM_BY_DIGIT:
            sym = SYMPTOM_BY_DIGIT[token]
        elif token in SYMPTOM_NAMES:
            sym = token
        else:
            continue
        if sym not in seen:
            seen.append(sym)
    return seen if seen else None


def parse_onset(message: str) -> date | None:
    if not message:
        return None
    text = message.strip().lower()
    today = date.today()
    if text == "today":
        return today
    if text == "yesterday":
        return today - timedelta(days=1)
    m = DDMM_RE.match(text)
    if not m:
        return None
    day_s, month_s, year_s = m.groups()
    try:
        day = int(day_s); month = int(month_s)
        if year_s is None:
            year = today.year
        else:
            year = int(year_s)
            if year < 100:
                year += 2000
        parsed = date(year, month, day)
    except ValueError:
        return None
    if parsed > today:
        return None
    return parsed
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/test_sms_parsers.py -v
```

Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add App/backend/sms_dialog.py App/backend/tests/test_sms_parsers.py
git commit -m "Phase F: SMS dialog parsers (case_count, symptoms, onset)"
```

### Task F.4: SMS state-machine — tests

**Files:**
- Create: `App/backend/tests/test_sms_dialog.py`

- [ ] **Step 1: Write the failing tests**

Create `App/backend/tests/test_sms_dialog.py`:

```python
"""Tests for the multi-turn SMS dialog at /sms."""

import re


def _sms(client, body, frm="+15551234567"):
    return client.post("/sms", data={"From": frm, "Body": body})


def _last_report(phone="+15551234567"):
    from database import connection
    with connection() as c:
        return c.execute(
            "SELECT * FROM illness_reports WHERE reporter_phone = ? "
            "ORDER BY report_id DESC LIMIT 1", (phone,)
        ).fetchone()


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
            "SELECT station_id, dialog_state FROM illness_reports "
            "WHERE reporter_phone = '+15551234567' ORDER BY report_id"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["station_id"] == 4
        assert rows[0]["dialog_state"] == "abandoned"
        assert rows[1]["station_id"] == 7
        assert rows[1]["dialog_state"] == "awaiting_case_count"


def test_labelling_fires_on_first_sms_only(client):
    """Insert a sensor reading so labelling has something to label."""
    from database import connection
    from datetime import datetime, timezone, timedelta
    with connection() as c:
        ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        c.execute(
            "INSERT INTO sensor_readings (station_id, recorded_at, ph, turbidity_ntu, "
            "temperature_c, rainfall_mm, provenance) "
            "VALUES (4, ?, 7.0, 5.0, 22.0, 0.0, 'test')", (ts,)
        )
    _sms(client, "station 4")
    with connection() as c:
        labels_after_first = c.execute("SELECT COUNT(*) FROM reading_labels").fetchone()[0]
    _sms(client, "3")
    _sms(client, "1,3")
    _sms(client, "today")
    with connection() as c:
        labels_after_complete = c.execute("SELECT COUNT(*) FROM reading_labels").fetchone()[0]
    assert labels_after_first == labels_after_complete  # no extra labels added by dialog
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/test_sms_dialog.py -v
```

Expected: FAIL — the existing /sms handles a single message, not a state machine.

### Task F.5: SMS state machine — implementation

**Files:**
- Modify: `App/backend/app.py`

- [ ] **Step 1: Replace the /sms route with the state-machine version**

Modify `App/backend/app.py`. Replace the existing `@app.post("/sms")` function entirely with:

```python
SMS_WINDOW_MINUTES = 30


def _find_open_conversation(conn, phone: str):
    """Return the most recent non-terminal report from this phone within window, or None."""
    if not phone:
        return None
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=SMS_WINDOW_MINUTES)).isoformat()
    return conn.execute(
        """
        SELECT * FROM illness_reports
        WHERE reporter_phone = ?
          AND received_at >= ?
          AND dialog_state IN ('awaiting_case_count','awaiting_symptoms','awaiting_onset')
        ORDER BY report_id DESC LIMIT 1
        """,
        (phone, cutoff),
    ).fetchone()


def _mark_abandoned(conn, report_id):
    conn.execute(
        "UPDATE illness_reports SET dialog_state = 'abandoned' WHERE report_id = ?",
        (report_id,),
    )


@app.post("/sms")
def sms_webhook():
    if not _verify_twilio_signature(request):
        return ("forbidden", 403)

    from sms_dialog import parse_case_count, parse_symptoms, parse_onset

    raw_message = request.form.get("Body", "") or ""
    reporter_phone = request.form.get("From", "") or ""
    now = datetime.now(timezone.utc)
    reply = MessagingResponse()

    is_stop = re.search(r"\bstop\b", raw_message, re.IGNORECASE) is not None
    station_id = _parse_station_id(raw_message)

    with connection() as conn:
        open_conv = _find_open_conversation(conn, reporter_phone)

        # --- STOP keyword ---------------------------------------------------
        if is_stop:
            if open_conv is None:
                reply.message("No active conversation to opt out of. Thank you.")
                return str(reply)
            _mark_abandoned(conn, open_conv["report_id"])
            reply.message("Opted out. We will no longer reply. Thank you.")
            return str(reply)

        # --- new station number while in conversation: abandon + restart ----
        if station_id is not None and open_conv is not None and station_id != open_conv["station_id"]:
            _mark_abandoned(conn, open_conv["report_id"])
            open_conv = None

        # --- no conversation: start one or store unparsed ------------------
        if open_conv is None:
            if station_id is None:
                # unparsed; same behaviour as before — record + ask for station
                conn.execute(
                    """
                    INSERT INTO illness_reports
                        (station_id, reporter_phone, raw_message, parser_version,
                         report_source, dialog_state)
                    VALUES (NULL, ?, ?, ?, 'sms', NULL)
                    """,
                    (reporter_phone, raw_message, STATION_PARSER_VERSION),
                )
                reply.message(
                    "We received your message but could not identify a station "
                    "number. Reply with the station number (e.g. '4'). Thank you."
                )
                return str(reply)

            station = conn.execute(
                "SELECT station_id, name FROM stations WHERE station_id = ?",
                (station_id,),
            ).fetchone()
            if station is None:
                conn.execute(
                    """
                    INSERT INTO illness_reports
                        (station_id, reporter_phone, raw_message, parser_version,
                         report_source, dialog_state)
                    VALUES (NULL, ?, ?, ?, 'sms', NULL)
                    """,
                    (reporter_phone, raw_message, STATION_PARSER_VERSION),
                )
                reply.message(
                    f"Station {station_id} is not in our system. Please check "
                    "the number and try again. Thank you."
                )
                return str(reply)

            cursor = conn.execute(
                """
                INSERT INTO illness_reports
                    (station_id, reporter_phone, raw_message, parser_version,
                     report_source, dialog_state)
                VALUES (?, ?, ?, ?, 'sms', 'awaiting_case_count')
                """,
                (station_id, reporter_phone, raw_message, STATION_PARSER_VERSION),
            )
            report_id = cursor.lastrowid
            labelled = label_readings_for_report(
                conn, report_id=report_id, station_id=station_id, report_time=now,
            )
            reply.message(
                f"Report received for {station['name']} (station {station_id}). "
                f"{labelled} reading(s) flagged. How many people are sick? "
                "Reply with a number."
            )
            return str(reply)

        # --- continue an in-progress conversation --------------------------
        report_id = open_conv["report_id"]
        state = open_conv["dialog_state"]

        if state == "awaiting_case_count":
            n = parse_case_count(raw_message)
            if n is None:
                reply.message(
                    "I didn't understand. How many people are sick? Reply with a number."
                )
                return str(reply)
            conn.execute(
                "UPDATE illness_reports SET case_count = ?, dialog_state = 'awaiting_symptoms' "
                "WHERE report_id = ?",
                (n, report_id),
            )
            reply.message(
                f"Noted, {n} cases. Which symptoms? Reply with numbers, e.g. '1,3'. "
                "1=diarrhoea 2=vomiting 3=fever 4=dehydration."
            )
            return str(reply)

        if state == "awaiting_symptoms":
            syms = parse_symptoms(raw_message)
            if syms is None:
                reply.message(
                    "I didn't understand. Reply with numbers, e.g. '1,3'. "
                    "1=diarrhoea 2=vomiting 3=fever 4=dehydration."
                )
                return str(reply)
            conn.execute(
                "UPDATE illness_reports SET symptoms = ?, dialog_state = 'awaiting_onset' "
                "WHERE report_id = ?",
                (json.dumps(syms), report_id),
            )
            reply.message(
                f"Noted: {', '.join(syms)}. When did symptoms start? "
                "Reply 'today', 'yesterday', or DD/MM."
            )
            return str(reply)

        if state == "awaiting_onset":
            onset = parse_onset(raw_message)
            if onset is None:
                reply.message(
                    "I didn't understand. Reply 'today', 'yesterday', or DD/MM."
                )
                return str(reply)
            conn.execute(
                "UPDATE illness_reports SET onset_date = ?, dialog_state = 'complete' "
                "WHERE report_id = ?",
                (onset.isoformat(), report_id),
            )
            reply.message(
                "Report complete. Stay safe. Reply STOP to opt out."
            )
            return str(reply)

        # Defensive — should not reach here for an open conversation.
        reply.message("Unexpected state. Reply STOP to opt out, or text a station number to start over.")
        return str(reply)
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/test_sms_dialog.py -v
```

Expected: all 10 PASS.

- [ ] **Step 3: Commit**

```bash
git add App/backend/app.py App/backend/tests/test_sms_dialog.py
git commit -m "Phase F: /sms multi-turn state machine"
```

### Task F.6: End-to-end verification of Phase F

- [ ] **Step 1: Full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests across all phases PASS.

- [ ] **Step 2: Manual smoke check (with TWILIO_VALIDATE_SIGNATURES=false)**

In one terminal: `python app.py`. In another:

```bash
BASE=http://localhost:5000
curl -X POST $BASE/sms -d "From=+15550001&Body=station 5"
curl -X POST $BASE/sms -d "From=+15550001&Body=4"
curl -X POST $BASE/sms -d "From=+15550001&Body=1,3"
curl -X POST $BASE/sms -d "From=+15550001&Body=today"
# Then view the report on the dashboard as gov:
# /dashboard → click the row → "Reporter's clinical assessment" absent (no risk_tier), "Estimated risk tier" + banner shown
```

- [ ] **Step 3: Final commit if any small fixes from smoke check**

If no issues, nothing to commit.

---

## Final verification

- [ ] **Run the entire test suite one more time:**

```bash
.venv/bin/pytest -v
```

Expected pass count (approximate): 60+ tests across all phases.

- [ ] **Push all commits to origin:**

```bash
git push origin main
```

- [ ] **Manual end-to-end demo run:**

1. Start Flask + simulator.
2. Sign in as `dr.smith` → file a report with tier=SEVERE, see History → map shows reports.
3. Sign in as `official.jones` → see report row with bright SEVERE pill; click → detail page shows reporter assessment, no banner; Close station → 🔒 appears.
4. Trigger an SMS via `curl` → multi-turn dialog → final report appears with estimated tier.

Plan complete.
