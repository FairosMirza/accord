"""The HTTP layer: CSRF protection, sign-in, and acting on requests through the API."""

from app.models import RequestStatus

CSRF = {"X-Requested-With": "accord"}


def sign_in(client, user):
    client.cookies.clear()
    response = client.post("/api/auth/demo", json={"user_id": user.id}, headers=CSRF)
    assert response.status_code == 200, response.text


def test_state_changing_calls_without_the_accord_header_are_blocked_even_when_signed_in(client, org, db):
    req = org.submit(org.engineer, org.office, 300)
    sign_in(client, org.tech_lead)  # the approver, signed in

    response = client.post(f"/api/requests/{req.ref}/approve", json={})  # what a cross-site form post would send

    assert response.status_code == 403
    assert response.json()["code"] == "csrf"
    db.refresh(req)
    assert req.status == RequestStatus.PENDING


def test_dashboard_needs_sign_in(client):
    response = client.get("/api/dashboard")

    assert response.status_code == 401


def test_request_you_cannot_see_looks_exactly_like_one_that_does_not_exist(client, org):
    hidden = org.submit(org.site_worker, org.office, 300)
    sign_in(client, org.engineer)

    response = client.get(f"/api/requests/{hidden.ref}")

    assert response.status_code == 404
    assert response.json() == client.get("/api/requests/AC-1").json()


def test_approver_can_approve_through_the_api_but_others_cannot(client, org):
    req = org.submit(org.engineer, org.office, 300)  # waits for the tech lead

    sign_in(client, org.coo)  # can see everything, but it isn't waiting for them
    response = client.post(f"/api/requests/{req.ref}/approve", json={}, headers=CSRF)
    assert response.status_code == 403

    sign_in(client, org.tech_lead)
    response = client.post(f"/api/requests/{req.ref}/approve", json={"comment": "Fine by me"}, headers=CSRF)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["steps"][0]["acted_by"]["id"] == org.tech_lead.id
    assert body["steps"][0]["comment"] == "Fine by me"
