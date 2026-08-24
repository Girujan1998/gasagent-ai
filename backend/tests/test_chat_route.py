from fastapi.testclient import TestClient

from app.api.routes.chat import get_chat_service
from app.main import app
from app.models.schemas import ChatMessage, EvStation, GasStation
from app.services.gemini_client import ChatError, ChatTurnResult

client = TestClient(app)


class FakeChatService:
    def __init__(
        self,
        reply: ChatMessage | None = None,
        error: Exception | None = None,
        gas_stations: list[GasStation] | None = None,
        ev_stations: list[EvStation] | None = None,
    ):
        self._reply = reply or ChatMessage(role="assistant", content="Hi!")
        self._error = error
        self._gas_stations = gas_stations or []
        self._ev_stations = ev_stations or []
        self.last_messages: list[ChatMessage] | None = None
        self.last_gas_location: tuple[float, float] | None = None
        self.last_ev_location: tuple[float, float] | None = None

    async def send(
        self,
        messages: list[ChatMessage],
        gas_location: tuple[float, float] | None = None,
        ev_location: tuple[float, float] | None = None,
    ) -> ChatTurnResult:
        self.last_messages = messages
        self.last_gas_location = gas_location
        self.last_ev_location = ev_location
        if self._error:
            raise self._error
        return ChatTurnResult(
            message=self._reply,
            gas_stations=self._gas_stations,
            ev_stations=self._ev_stations,
        )


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


def test_forwards_the_gas_location_field_to_the_service():
    fake_service = FakeChatService()
    app.dependency_overrides[get_chat_service] = lambda: fake_service
    try:
        response = client.post(
            "/api/v1/chat",
            json={
                "messages": [{"role": "user", "content": "gas near me?"}],
                "gas_location": {"lat": 1.0, "lon": 2.0},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake_service.last_gas_location == (1.0, 2.0)
    assert fake_service.last_ev_location is None


def test_forwards_the_ev_location_field_to_the_service():
    fake_service = FakeChatService()
    app.dependency_overrides[get_chat_service] = lambda: fake_service
    try:
        response = client.post(
            "/api/v1/chat",
            json={
                "messages": [{"role": "user", "content": "EV chargers near me?"}],
                "ev_location": {"lat": 3.0, "lon": 4.0},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake_service.last_ev_location == (3.0, 4.0)
    assert fake_service.last_gas_location is None


def test_works_without_either_location_field():
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
    assert fake_service.last_gas_location is None
    assert fake_service.last_ev_location is None


def test_forwards_gas_and_ev_stations_from_the_service_into_the_response():
    fake_service = FakeChatService(
        gas_stations=[GasStation(station_id="1", name="Shell")],
        ev_stations=[EvStation(station_id="2", name="ChargePoint")],
    )
    app.dependency_overrides[get_chat_service] = lambda: fake_service
    try:
        response = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "gas and ev near me?"}]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["gas_stations"][0]["name"] == "Shell"
    assert body["ev_stations"][0]["name"] == "ChargePoint"


def test_returns_empty_station_lists_by_default():
    fake_service = FakeChatService()
    app.dependency_overrides[get_chat_service] = lambda: fake_service
    try:
        response = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
    finally:
        app.dependency_overrides.clear()

    body = response.json()
    assert body["gas_stations"] == []
    assert body["ev_stations"] == []
