import pytest
from decimal import Decimal


class TestCreateExpense:
    def test_create_expense_success(self, client, auth_headers):
        response = client.post(
            "/api/expenses",
            headers=auth_headers,
            json={
                "name": "Lunch",
                "amount": 12.50,
                "category": "Food",
                "date": "2026-05-28",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Lunch"
        assert float(data["amount"]) == 12.50
        assert data["category"] == "Food"

    def test_create_expense_missing_fields(self, client, auth_headers):
        response = client.post(
            "/api/expenses",
            headers=auth_headers,
            json={"name": "Lunch"},
        )
        assert response.status_code == 422

    def test_create_expense_unauthorized(self, client):
        response = client.post(
            "/api/expenses",
            json={
                "name": "Lunch",
                "amount": 12.50,
                "category": "Food",
                "date": "2026-05-28",
            },
        )
        assert response.status_code in [401, 403]


class TestSoftDeleteExpense:
    def test_soft_delete_success(self, client, auth_headers):
        create_response = client.post(
            "/api/expenses",
            headers=auth_headers,
            json={
                "name": "Coffee",
                "amount": 5.00,
                "category": "Food",
                "date": "2026-05-28",
            },
        )
        expense_id = create_response.json()["id"]

        response = client.patch(
            f"/api/expenses/{expense_id}/delete",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["deleted_at"] is not None

    def test_soft_delete_nonexistent_expense(self, client, auth_headers):
        response = client.patch(
            "/api/expenses/99999/delete",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_soft_delete_already_deleted(self, client, auth_headers):
        create_response = client.post(
            "/api/expenses",
            headers=auth_headers,
            json={
                "name": "Already deleted",
                "amount": 10.00,
                "category": "Food",
                "date": "2026-05-28",
            },
        )
        expense_id = create_response.json()["id"]

        client.patch(f"/api/expenses/{expense_id}/delete", headers=auth_headers)
        response = client.patch(
            f"/api/expenses/{expense_id}/delete",
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_soft_delete_excludes_from_list(self, client, auth_headers):
        create_response = client.post(
            "/api/expenses",
            headers=auth_headers,
            json={
                "name": "To be deleted",
                "amount": 15.00,
                "category": "Food",
                "date": "2026-05-28",
            },
        )
        expense_id = create_response.json()["id"]
        client.patch(f"/api/expenses/{expense_id}/delete", headers=auth_headers)

        list_response = client.get("/api/expenses", headers=auth_headers)
        expense_ids = [e["id"] for e in list_response.json()["expenses"]]
        assert expense_id not in expense_ids


class TestRestoreExpense:
    def test_restore_success(self, client, auth_headers):
        create_response = client.post(
            "/api/expenses",
            headers=auth_headers,
            json={
                "name": "To restore",
                "amount": 20.00,
                "category": "Food",
                "date": "2026-05-28",
            },
        )
        expense_id = create_response.json()["id"]
        client.patch(f"/api/expenses/{expense_id}/delete", headers=auth_headers)

        response = client.post(
            f"/api/expenses/{expense_id}/restore",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is False
        assert data["deleted_at"] is None

    def test_restore_nonexistent_expense(self, client, auth_headers):
        response = client.post(
            "/api/expenses/99999/restore",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_restore_not_deleted(self, client, auth_headers):
        create_response = client.post(
            "/api/expenses",
            headers=auth_headers,
            json={
                "name": "Active expense",
                "amount": 25.00,
                "category": "Food",
                "date": "2026-05-28",
            },
        )
        expense_id = create_response.json()["id"]

        response = client.post(
            f"/api/expenses/{expense_id}/restore",
            headers=auth_headers,
        )
        assert response.status_code == 200


class TestPermanentDelete:
    def test_permanent_delete_success(self, client, auth_headers):
        create_response = client.post(
            "/api/expenses",
            headers=auth_headers,
            json={
                "name": "To permanently delete",
                "amount": 30.00,
                "category": "Food",
                "date": "2026-05-28",
            },
        )
        expense_id = create_response.json()["id"]
        client.patch(f"/api/expenses/{expense_id}/delete", headers=auth_headers)

        response = client.delete(
            f"/api/expenses/{expense_id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "permanently deleted" in response.json()["message"]

    def test_permanent_delete_active_expense_fails(self, client, auth_headers):
        create_response = client.post(
            "/api/expenses",
            headers=auth_headers,
            json={
                "name": "Active expense",
                "amount": 35.00,
                "category": "Food",
                "date": "2026-05-28",
            },
        )
        expense_id = create_response.json()["id"]

        response = client.delete(
            f"/api/expenses/{expense_id}",
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "recycle bin" in response.json()["detail"].lower()

    def test_permanent_delete_nonexistent(self, client, auth_headers):
        response = client.delete(
            "/api/expenses/99999",
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestRecycleBin:
    def test_list_recycle_bin(self, client, auth_headers):
        for i in range(3):
            create_response = client.post(
                "/api/expenses",
                headers=auth_headers,
                json={
                    "name": f"Expense {i}",
                    "amount": 10.00 * (i + 1),
                    "category": "Food",
                    "date": "2026-05-28",
                },
            )
            expense_id = create_response.json()["id"]
            client.patch(f"/api/expenses/{expense_id}/delete", headers=auth_headers)

        response = client.get("/api/expenses/recycle", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["expenses"]) == 3
        assert data["pagination"]["total"] == 3

    def test_recycle_bin_empty(self, client, auth_headers):
        response = client.get("/api/expenses/recycle", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["expenses"]) == 0
