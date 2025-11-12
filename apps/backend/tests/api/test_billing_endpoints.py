"""API integration tests for billing endpoints."""

import os
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
import stripe
from fastapi import status

from specscribe.api.rate_limiting import billing_checkout_rate_limiter, billing_portal_rate_limiter
from specscribe.core.database_models import SubscriptionTable, UserTable
from specscribe.core.storage import DatabaseManager


@pytest.fixture
def mock_stripe_service():
    """Mock StripeService for dependency injection."""
    with patch("specscribe.api.routes.billing.get_stripe_service") as mock:
        service = Mock()
        mock.return_value = service
        yield service


@pytest.fixture
def reset_rate_limiters():
    """Reset rate limiters between tests."""
    billing_checkout_rate_limiter.requests.clear()
    billing_portal_rate_limiter.requests.clear()
    yield
    billing_checkout_rate_limiter.requests.clear()
    billing_portal_rate_limiter.requests.clear()


# ============================================================================
# POST /billing/create-checkout-session Tests
# ============================================================================


class TestCreateCheckoutSession:
    """Test create checkout session endpoint."""

    def test_creates_checkout_session_monthly(self, client, mock_stripe_service, reset_rate_limiters):
        """Test creating checkout session with monthly plan."""
        mock_stripe_service.create_customer.return_value = "cus_test123"
        mock_stripe_service.get_price_id.return_value = "price_monthly_123"
        mock_stripe_service.create_checkout_session.return_value = ("cs_test123", "https://checkout.stripe.com/123")

        response = client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "month"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["checkout_url"] == "https://checkout.stripe.com/123"
        mock_stripe_service.create_customer.assert_called_once()
        mock_stripe_service.get_price_id.assert_called_once_with("month")

    def test_creates_checkout_session_annual(self, client, mock_stripe_service, reset_rate_limiters):
        """Test creating checkout session with annual plan."""
        mock_stripe_service.create_customer.return_value = "cus_test123"
        mock_stripe_service.get_price_id.return_value = "price_annual_123"
        mock_stripe_service.create_checkout_session.return_value = ("cs_test456", "https://checkout.stripe.com/456")

        response = client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "year"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["checkout_url"] == "https://checkout.stripe.com/456"
        mock_stripe_service.get_price_id.assert_called_once_with("year")

    def test_reuses_existing_customer(self, client, test_db, mock_stripe_service, reset_rate_limiters):
        """Test that existing Stripe customer is reused."""
        # Set up user with existing Stripe customer ID
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_existing_123"
            session.commit()

        mock_stripe_service.get_price_id.return_value = "price_monthly_123"
        mock_stripe_service.create_checkout_session.return_value = ("cs_test789", "https://checkout.stripe.com/789")

        response = client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "month"})

        assert response.status_code == status.HTTP_200_OK
        mock_stripe_service.create_customer.assert_not_called()
        mock_stripe_service.create_checkout_session.assert_called_once()

    def test_validates_plan_interval(self, client, reset_rate_limiters):
        """Test plan_interval validation."""
        response = client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "invalid"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "must be 'month' or 'year'" in response.json()["detail"]

    def test_handles_missing_plan_interval(self, client, reset_rate_limiters):
        """Test missing plan_interval field."""
        response = client.post("/api/v1/billing/create-checkout-session", json={})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_uses_frontend_url_from_env(self, client, mock_stripe_service, reset_rate_limiters, monkeypatch):
        """Test that FRONTEND_URL environment variable is used."""
        monkeypatch.setenv("FRONTEND_URL", "https://example.com")
        mock_stripe_service.create_customer.return_value = "cus_test123"
        mock_stripe_service.get_price_id.return_value = "price_monthly_123"
        mock_stripe_service.create_checkout_session.return_value = ("cs_test", "https://checkout.stripe.com/test")

        response = client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "month"})

        assert response.status_code == status.HTTP_200_OK
        # Verify success_url and cancel_url were passed correctly
        call_args = mock_stripe_service.create_checkout_session.call_args
        assert "https://example.com/billing?success=true" in str(call_args)
        assert "https://example.com/billing?canceled=true" in str(call_args)

    def test_falls_back_to_localhost_when_no_frontend_url(self, client, mock_stripe_service, reset_rate_limiters):
        """Test fallback to localhost when FRONTEND_URL not set."""
        # Remove FRONTEND_URL if set
        original_url = os.environ.get("FRONTEND_URL")
        if "FRONTEND_URL" in os.environ:
            del os.environ["FRONTEND_URL"]

        try:
            mock_stripe_service.create_customer.return_value = "cus_test123"
            mock_stripe_service.get_price_id.return_value = "price_monthly_123"
            mock_stripe_service.create_checkout_session.return_value = ("cs_test", "https://checkout.stripe.com/test")

            response = client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "month"})

            assert response.status_code == status.HTTP_200_OK
            call_args = mock_stripe_service.create_checkout_session.call_args
            assert "localhost:3000" in str(call_args)
        finally:
            # Restore original value
            if original_url:
                os.environ["FRONTEND_URL"] = original_url


# ============================================================================
# Rate Limiting Tests for Checkout
# ============================================================================


class TestCheckoutRateLimiting:
    """Test rate limiting for checkout endpoint."""

    def test_enforces_rate_limit_5_per_hour(self, client, mock_stripe_service, reset_rate_limiters):
        """Test checkout rate limit of 5 requests per hour."""
        mock_stripe_service.create_customer.return_value = "cus_test123"
        mock_stripe_service.get_price_id.return_value = "price_monthly_123"
        mock_stripe_service.create_checkout_session.return_value = ("cs_test", "https://checkout.stripe.com/test")

        # First 5 requests should succeed
        for _ in range(5):
            response = client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "month"})
            assert response.status_code == status.HTTP_200_OK

        # 6th request should be rate limited
        response = client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "month"})
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "rate_limit_exceeded" in response.json()["detail"]["error"]

    def test_rate_limit_includes_retry_after_header(self, client, mock_stripe_service, reset_rate_limiters):
        """Test rate limit response includes Retry-After header."""
        mock_stripe_service.create_customer.return_value = "cus_test123"
        mock_stripe_service.get_price_id.return_value = "price_monthly_123"
        mock_stripe_service.create_checkout_session.return_value = ("cs_test", "https://checkout.stripe.com/test")

        # Exhaust rate limit
        for _ in range(5):
            client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "month"})

        # Check rate limited response
        response = client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "month"})
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "Retry-After" in response.headers
        assert int(response.headers["Retry-After"]) > 0


# ============================================================================
# POST /billing/create-portal-session Tests
# ============================================================================


class TestCreatePortalSession:
    """Test create portal session endpoint."""

    def test_creates_portal_session(self, client, test_db, mock_stripe_service, reset_rate_limiters):
        """Test creating portal session for user with customer ID."""
        # Set up user with Stripe customer ID
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        mock_stripe_service.create_portal_session.return_value = "https://billing.stripe.com/session_test123"

        response = client.post("/api/v1/billing/create-portal-session")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["portal_url"] == "https://billing.stripe.com/session_test123"
        mock_stripe_service.create_portal_session.assert_called_once()

    def test_fails_when_no_customer_id(self, client, reset_rate_limiters):
        """Test portal session fails when user has no Stripe customer."""
        response = client.post("/api/v1/billing/create-portal-session")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "has no Stripe customer" in response.json()["detail"]

    def test_uses_frontend_url_for_return(self, client, test_db, mock_stripe_service, reset_rate_limiters, monkeypatch):
        """Test that return_url uses FRONTEND_URL."""
        monkeypatch.setenv("FRONTEND_URL", "https://example.com")

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        mock_stripe_service.create_portal_session.return_value = "https://billing.stripe.com/session"

        response = client.post("/api/v1/billing/create-portal-session")

        assert response.status_code == status.HTTP_200_OK
        call_args = mock_stripe_service.create_portal_session.call_args
        assert "https://example.com/billing" in str(call_args)


# ============================================================================
# Rate Limiting Tests for Portal
# ============================================================================


class TestPortalRateLimiting:
    """Test rate limiting for portal endpoint."""

    def test_enforces_rate_limit_10_per_hour(self, client, test_db, mock_stripe_service, reset_rate_limiters):
        """Test portal rate limit of 10 requests per hour."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        mock_stripe_service.create_portal_session.return_value = "https://billing.stripe.com/session"

        # First 10 requests should succeed
        for _ in range(10):
            response = client.post("/api/v1/billing/create-portal-session")
            assert response.status_code == status.HTTP_200_OK

        # 11th request should be rate limited
        response = client.post("/api/v1/billing/create-portal-session")
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "rate_limit_exceeded" in response.json()["detail"]["error"]


# ============================================================================
# GET /billing/subscription Tests
# ============================================================================


class TestGetSubscription:
    """Test get subscription endpoint."""

    def test_returns_active_subscription(self, client, test_db):
        """Test retrieving user's active subscription."""
        # Create subscription in database
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            subscription = SubscriptionTable(
                user_id=user.id,
                stripe_customer_id="cus_test123",
                stripe_subscription_id="sub_test123",
                status="active",
                plan_interval="month",
                current_period_start=datetime(2024, 1, 1, tzinfo=UTC),
                current_period_end=datetime(2024, 2, 1, tzinfo=UTC),
                cancel_at_period_end=False,
            )
            session.add(subscription)
            session.commit()

        response = client.get("/api/v1/billing/subscription")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "active"
        assert data["plan_interval"] == "month"
        assert data["cancel_at_period_end"] is False
        assert "2024-02-01" in data["current_period_end"]

    def test_returns_null_when_no_subscription(self, client):
        """Test returns null when user has no subscription."""
        response = client.get("/api/v1/billing/subscription")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() is None

    def test_returns_canceled_subscription(self, client, test_db):
        """Test retrieving canceled subscription."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            subscription = SubscriptionTable(
                user_id=user.id,
                stripe_customer_id="cus_test123",
                stripe_subscription_id="sub_test123",
                status="canceled",
                plan_interval="year",
                current_period_start=datetime(2024, 1, 1, tzinfo=UTC),
                current_period_end=datetime(2025, 1, 1, tzinfo=UTC),
                cancel_at_period_end=True,
            )
            session.add(subscription)
            session.commit()

        response = client.get("/api/v1/billing/subscription")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "canceled"
        assert data["plan_interval"] == "year"
        assert data["cancel_at_period_end"] is True

    def test_formats_period_end_as_isoformat(self, client, test_db):
        """Test current_period_end is formatted as ISO format."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            subscription = SubscriptionTable(
                user_id=user.id,
                stripe_customer_id="cus_test123",
                stripe_subscription_id="sub_test123",
                status="active",
                plan_interval="month",
                current_period_start=datetime(2024, 6, 15, 10, 30, 45, tzinfo=UTC),
                current_period_end=datetime(2024, 7, 15, 10, 30, 45, tzinfo=UTC),
                cancel_at_period_end=False,
            )
            session.add(subscription)
            session.commit()

        response = client.get("/api/v1/billing/subscription")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Should be ISO format (datetime.isoformat() doesn't include timezone suffix for naive datetimes)
        assert data["current_period_end"] == "2024-07-15T10:30:45"


# ============================================================================
# Security Tests
# ============================================================================


class TestBillingSecurityAndEdgeCases:
    """Test security and edge cases for billing endpoints."""

    def test_checkout_validates_stripe_price_id_env_var(self, client, mock_stripe_service, reset_rate_limiters):
        """Test checkout fails gracefully when Stripe price ID not configured."""
        mock_stripe_service.create_customer.return_value = "cus_test123"
        mock_stripe_service.get_price_id.side_effect = ValueError(
            "STRIPE_PRICE_ID_MONTHLY environment variable required"
        )

        response = client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "month"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "environment variable required" in response.json()["detail"]

    def test_portal_handles_stripe_api_errors(self, client, test_db, mock_stripe_service, reset_rate_limiters):
        """Test portal handles Stripe API errors gracefully."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        mock_stripe_service.create_portal_session.side_effect = stripe.StripeError("API Error")

        # Stripe errors propagate as 500 Internal Server Error
        response = client.post("/api/v1/billing/create-portal-session")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_checkout_handles_stripe_customer_creation_failure(self, client, mock_stripe_service, reset_rate_limiters):
        """Test checkout handles customer creation failures."""
        mock_stripe_service.create_customer.side_effect = stripe.StripeError("Failed to create customer")

        # Stripe errors propagate as 500 Internal Server Error
        response = client.post("/api/v1/billing/create-checkout-session", json={"plan_interval": "month"})
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
