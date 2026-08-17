from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_autocomplete_returns_empty_results_under_three_characters():
    # Short-circuits before any network call, so this is safe to hit for
    # real — no mocking needed.
    response = client.get("/api/v1/locations/autocomplete", params={"query": "ab"})

    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_autocomplete_requires_a_query_param():
    response = client.get("/api/v1/locations/autocomplete")

    assert response.status_code == 422
