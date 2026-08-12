import pytest
from decimal import Decimal


class TestHealthCheck:
    def test_health_endpoint(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_health_db_endpoint(self, client):
        response = client.get("/health/db")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["dependency"] == "database"


class TestProfile:
    def test_update_profile(self, client, auth_headers):
        response = client.patch(
            "/api/profile",
            headers=auth_headers,
            json={"allowance": 1000.00},
        )
        assert response.status_code == 200
        data = response.json()
        assert float(data["allowance"]) == 1000.00

    def test_get_state(self, client, auth_headers):
        response = client.get("/api/state", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "profile" in data
        assert "categories" in data
        assert "expenses" in data
        assert "goal" in data


class TestCategories:
    def test_update_category_budget(self, client, auth_headers, db):
        from backend.models import Category
        from sqlalchemy import select

        category = db.scalar(
            select(Category).where(Category.name == "Food")
        )
        assert category is not None

        response = client.patch(
            f"/api/categories/{category.id}",
            headers=auth_headers,
            json={"budget": 200.00},
        )
        assert response.status_code == 200
        data = response.json()
        assert float(data["budget"]) == 200.00


class TestGoal:
    def test_update_goal(self, client, auth_headers):
        response = client.put(
            "/api/goal",
            headers=auth_headers,
            json={
                "name": "New laptop",
                "target": 1000.00,
                "saved": 250.00,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New laptop"
        assert float(data["target"]) == 1000.00
        assert float(data["saved"]) == 250.00


class TestSettings:
    def test_update_settings(self, client, auth_headers):
        response = client.patch(
            "/api/settings",
            headers=auth_headers,
            json={
                "country": "Nigeria",
                "savings_currencies": [{"currency": "NGN", "amount": 50000}],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["country"] == "Nigeria"


class TestNotifications:
    def test_list_notifications(self, client, auth_headers):
        response = client.get("/api/notifications", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)
