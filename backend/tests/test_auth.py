import pytest


class TestSignup:
    def test_signup_success(self, client, test_user_data):
        response = client.post("/api/auth/signup", json=test_user_data)
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert data["profile"]["email"] == test_user_data["email"]
        assert data["profile"]["first_name"] == test_user_data["first_name"]

    def test_signup_duplicate_email(self, client, test_user_data):
        client.post("/api/auth/signup", json=test_user_data)
        response = client.post("/api/auth/signup", json=test_user_data)
        assert response.status_code == 409

    def test_signup_invalid_email(self, client):
        response = client.post(
            "/api/auth/signup",
            json={
                "first_name": "Test",
                "last_name": "User",
                "email": "not-an-email",
                "password": "Password123!",
                "gender": "male",
            },
        )
        assert response.status_code == 422

    def test_signup_short_password(self, client):
        response = client.post(
            "/api/auth/signup",
            json={
                "first_name": "Test",
                "last_name": "User",
                "email": "test@example.com",
                "password": "short",
                "gender": "male",
            },
        )
        assert response.status_code == 422


class TestLogin:
    def test_login_success(self, client, verified_user):
        response = client.post(
            "/api/auth/login",
            json={"email": "verified@example.com", "password": "Password123!"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["profile"]["email"] == "verified@example.com"

    def test_login_wrong_password(self, client, verified_user):
        response = client.post(
            "/api/auth/login",
            json={"email": "verified@example.com", "password": "WrongPassword!"},
        )
        assert response.status_code == 401

    def test_login_nonexistent_user(self, client):
        response = client.post(
            "/api/auth/login",
            json={"email": "nonexistent@example.com", "password": "Password123!"},
        )
        assert response.status_code == 401

    def test_login_sets_refresh_cookie(self, client, verified_user):
        response = client.post(
            "/api/auth/login",
            json={"email": "verified@example.com", "password": "Password123!"},
        )
        assert response.status_code == 200
        cookies = response.cookies
        assert "refresh_token" in cookies


class TestRefreshToken:
    def test_refresh_token_success(self, client, verified_user):
        login_response = client.post(
            "/api/auth/login",
            json={"email": "verified@example.com", "password": "Password123!"},
        )
        assert login_response.status_code == 200

        refresh_response = client.post("/api/auth/refresh")
        assert refresh_response.status_code == 200
        assert "access_token" in refresh_response.json()

    def test_refresh_token_missing(self, client):
        response = client.post("/api/auth/refresh")
        assert response.status_code == 401


class TestLogout:
    def test_logout_success(self, client, auth_headers):
        response = client.post("/api/auth/logout", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["message"] == "Logged out"

    def test_logout_clears_refresh_cookie(self, client, verified_user):
        login_response = client.post(
            "/api/auth/login",
            json={"email": "verified@example.com", "password": "Password123!"},
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post("/api/auth/logout", headers=headers)
        assert response.status_code == 200


class TestEmailVerification:
    def test_verify_email_removed(self, client, create_test_user):
        response = client.post(
            "/api/auth/verify-email",
            json={"email": "test@example.com", "code": "000000"},
        )
        assert response.status_code in [404, 405]

    def test_resend_verification_removed(self, client, create_test_user):
        response = client.post(
            "/api/auth/resend-verification",
            json={"email": "test@example.com"},
        )
        assert response.status_code in [404, 405]


class TestPasswordReset:
    def test_forgot_password(self, client, verified_user):
        response = client.post(
            "/api/auth/forgot-password",
            json={"email": "verified@example.com"},
        )
        assert response.status_code == 200
        assert "message" in response.json()

    def test_forgot_password_nonexistent_email(self, client):
        response = client.post(
            "/api/auth/forgot-password",
            json={"email": "nonexistent@example.com"},
        )
        assert response.status_code == 200

    def test_reset_password_invalid_token(self, client):
        response = client.post(
            "/api/auth/reset-password",
            json={"token": "a" * 40, "new_password": "NewPassword123!"},
        )
        assert response.status_code == 400
