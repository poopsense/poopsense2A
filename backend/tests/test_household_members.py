OWNER = {"X-Household-Key": "household-secret"}
VIEWER = {"X-Household-Key": "viewer-secret"}
URL = "/api/v1/households/hh_001/members"


def test_owner_can_add_member_and_duplicate_name_is_rejected(client):
    created = client.post(URL, headers=OWNER, json={"display_name": "奶奶"})
    assert created.status_code == 200
    assert created.json()["display_name"] == "奶奶"
    assert created.json()["linked_to_current_user"] is False
    assert any(item["member_id"] == created.json()["member_id"]
               for item in client.get(URL, headers=OWNER).json())
    duplicate = client.post(URL, headers=OWNER, json={"display_name": "奶奶"})
    assert duplicate.status_code == 409


def test_viewer_cannot_add_household_member(client):
    response = client.post(URL, headers=VIEWER, json={"display_name": "越权成员"})
    assert response.status_code == 403
