from fastapi.testclient import TestClient

from app.api.routes.chat import get_chat_service
from app.main import app
from app.models.schemas import ChatMessage
from app.services.chat_client import ChatError

client = TestClient(app)


class FakeChatService:
    def __init__(self, reply: ChatMessage | None = None, error: Exception | None = None):
        self._reply = reply or ChatMessage(role="assistant", content="Hi!")
        self._error = error
        self.last_messages: list[ChatMessage] | None = None
        self.last_location: tuple[float, float] | None = None

    async def send(
        self,
        messages: list[ChatMessage],
        location: tuple[float, float] | None = None,
    ) -> ChatMessage:
        self.last_messages = messages
        self.last_location = location
        if self._error:
            raise self._error
        return self._reply


def test_returns_the_agents_reply():
    fake_service = FakeChatService(reply=ChatMessage(role="assistant", content="Hello!"))
    app.dependency_overrides[get_chat_service] = lambda: fake_service
    try:
        response = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == {"role": "assistant", "content": "Hello!"}
    assert fake_service.last_messages == [ChatMessage(role="user", content="Hi")]


def test_translates_a_chat_error_into_a_502():
    app.dependency_overrides[get_chat_service] = lambda: FakeChatService(
        error=ChatError("Invalid API Key")
    )
    try:
        response = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["detail"] == "Invalid API Key"


def test_requires_a_messages_list():
    response = client.post("/api/v1/chat", json={})
    assert response.status_code == 422


def test_forwards_the_location_field_to_the_service():
    fake_service = FakeChatService()
    app.dependency_overrides[get_chat_service] = lambda: fake_service
    try:
        response = client.post(
            "/api/v1/chat",
            json={
                "messages": [{"role": "user", "content": "gas near me?"}],
                "location": {"lat": 1.0, "lon": 2.0},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake_service.last_location == (1.0, 2.0)


def test_works_without_a_location_field():
    fake_service = FakeChatService()
    app.dependency_overrides[get_chat_service] = lambda: fake_service
    try:
        response = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake_service.last_location is None
