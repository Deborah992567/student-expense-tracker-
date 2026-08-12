import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.database import Base, get_db
from backend.main import app
from backend.models import User, Category, Goal, UserSettings

TEST_DATABASE_URL = "sqlite:///./test_student_expense.db"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def test_user_data():
    return {
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        "password": "Password123!",
        "gender": "male",
    }


@pytest.fixture
def create_test_user(client, test_user_data):
    response = client.post("/api/auth/signup", json=test_user_data)
    assert response.status_code == 201
    data = response.json()
    return data


@pytest.fixture
def verified_user(client, db):
    from backend.auth import hash_password

    user = User(
        name="Verified User",
        first_name="Verified",
        last_name="User",
        email="verified@example.com",
        password_hash=hash_password("Password123!"),
        email_verified=True,
        role="student",
    )
    db.add(user)
    db.flush()

    default_categories = [
        ("Food", 0, "#0f9f9a"),
        ("Transport", 0, "#2563eb"),
        ("Books", 0, "#7c3aed"),
        ("Rent", 0, "#159947"),
        ("Social", 0, "#c18400"),
    ]
    for name, budget, color in default_categories:
        db.add(Category(user_id=user.id, name=name, budget=budget, color=color))

    db.add(Goal(user_id=user.id, name="Emergency fund", target=600, saved=0))
    db.add(UserSettings(user_id=user.id, country="United States", savings_currencies=[]))
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_token(client, verified_user):
    response = client.post(
        "/api/auth/login",
        json={"email": "verified@example.com", "password": "Password123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}
