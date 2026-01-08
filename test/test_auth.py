import pytest
from fastapi.testclient import TestClient
from web.user import router
from fastapi import FastAPI

# Создаем FastAPI приложение и подключаем роутер
app = FastAPI()
app.include_router(router)

client = TestClient(app)

# Пользователь из fake/user.py
TEST_USER = {
    "username": "kwiiobo",
    "password": "abc"  # plain password, как в fake
}

def test_get_token_success():
    response = client.post("/user/token", data=TEST_USER)
    assert response.status_code == 200
    json_data = response.json()
    assert "access_token" in json_data
    assert json_data["token_type"] == "bearer"

def test_get_token_wrong_password():
    response = client.post("/user/token", data={
        "username": TEST_USER["username"],
        "password": "wrong"
    })
    assert response.status_code == 401

def test_access_token_endpoint():
    # Сначала получаем токен
    response = client.post("/user/token", data=TEST_USER)
    token = response.json()["access_token"]

    # Используем токен для доступа
    headers = {"Authorization": f"Bearer {token}"}
    response2 = client.get("/user/token", headers=headers)
    assert response2.status_code == 200
    assert response2.json()["token"] == token
