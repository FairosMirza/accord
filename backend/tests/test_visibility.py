"""Who can see which requests (permissions.visibility_clause and can_view)."""

import pytest


@pytest.fixture
def trainee(org):
    """A trainee in People & Culture, supervised by the Accra site worker, who reports to the site manager.

    For the trainee's requests the site worker approves, the site manager is a skip-level manager and
    the head of People is the department head: three different people, none of whom sees everything.
    """
    return org.add_user("trainee", "Kojo Boateng", department="people", site="accra", manager="site_worker")


def test_employees_see_only_their_own_requests(org):
    own = org.submit(org.engineer, org.office, 300)
    org.submit(org.site_worker, org.office, 300)
    org.submit(org.people_head, org.office, 300)

    assert org.visible_refs(org.engineer) == {own.ref}


def test_managers_see_requests_from_their_whole_reporting_line(org, trainee):
    req = org.submit(trainee, org.office, 300)
    outside_the_team = org.submit(org.engineer, org.office, 300)

    assert org.approvers(req) == ["site_worker"]  # so the site manager sees it as a manager, not as an approver
    assert org.visible_refs(org.site_mgr) == {req.ref}
    assert outside_the_team.ref not in org.visible_refs(org.site_mgr)


def test_department_heads_see_requests_from_their_department(org, trainee):
    req = org.submit(trainee, org.office, 300)  # neither approved by nor reporting to the head of People
    other_department = org.submit(org.engineer, org.office, 300)

    assert org.can_see(org.people_head, req)
    assert not org.can_see(org.people_head, other_department)


def test_confidential_request_is_hidden_from_managers_and_department_heads_but_not_approver_or_finance(org, trainee):
    req = org.submit(trainee, org.legal, 300)

    assert req.is_confidential  # legal services are confidential by default
    expected = {
        "site_worker": True,  # approver
        "clerk": True,  # finance
        "auditor": True,
        "site_mgr": False,  # manager
        "people_head": False,  # department head
    }
    assert {key: org.can_see(org.users[key], req) for key in expected} == expected


def test_drafts_are_visible_only_to_their_author_even_for_see_everything_roles(org):
    draft = org.draft(org.engineer, org.office, 300)

    expected = {
        "engineer": True,
        "tech_lead": False,  # line manager and administrator
        "ceo": False,
        "clerk": False,
        "auditor": False,
    }
    assert {key: org.can_see(org.users[key], draft) for key in expected} == expected
