"""Unit tests for StripeService."""

from unittest.mock import Mock, patch

import pytest
import stripe
from stripe import APIConnectionError, RateLimitError, SignatureVerificationError
from tenacity import RetryError

from specscribe.core.services.stripe_service import StripeService


class TestStripeServiceInitialization:
    """Test StripeService initialization."""

    def test_init_with_valid_api_key(self, monkeypatch):
        """Test initialization with valid STRIPE_SECRET_KEY."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_valid_key")
        _ = StripeService()
        assert stripe.api_key == "sk_test_valid_key"

    def test_init_without_api_key_raises_error(self, monkeypatch):
        """Test initialization without STRIPE_SECRET_KEY raises ValueError."""
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        with pytest.raises(ValueError, match="STRIPE_SECRET_KEY environment variable is required"):
            StripeService()

    def test_init_with_empty_api_key_raises_error(self, monkeypatch):
        """Test initialization with empty STRIPE_SECRET_KEY raises ValueError."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "")
        with pytest.raises(ValueError, match="STRIPE_SECRET_KEY environment variable is required"):
            StripeService()


class TestStripeServiceCreateCustomer:
    """Test StripeService.create_customer method."""

    @patch("stripe.Customer.create")
    def test_create_customer_with_email_only(self, mock_create, monkeypatch):
        """Test creating customer with email only."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_customer = Mock()
        mock_customer.id = "cus_test123"
        mock_create.return_value = mock_customer

        service = StripeService()
        customer_id = service.create_customer(email="test@example.com")

        assert customer_id == "cus_test123"
        mock_create.assert_called_once_with(email="test@example.com")

    @patch("stripe.Customer.create")
    def test_create_customer_with_all_fields(self, mock_create, monkeypatch):
        """Test creating customer with email, name, and metadata."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_customer = Mock()
        mock_customer.id = "cus_test456"
        mock_create.return_value = mock_customer

        service = StripeService()
        customer_id = service.create_customer(
            email="test@example.com", name="Test User", metadata={"user_id": "user123"}
        )

        assert customer_id == "cus_test456"
        mock_create.assert_called_once_with(email="test@example.com", name="Test User", metadata={"user_id": "user123"})

    @patch("stripe.Customer.create")
    def test_create_customer_retries_on_rate_limit(self, mock_create, monkeypatch):
        """Test create_customer retries on RateLimitError."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_customer = Mock()
        mock_customer.id = "cus_test789"

        mock_create.side_effect = [RateLimitError("Rate limit"), mock_customer]

        service = StripeService()
        customer_id = service.create_customer(email="test@example.com")

        assert customer_id == "cus_test789"
        assert mock_create.call_count == 2

    @patch("stripe.Customer.create")
    def test_create_customer_retries_on_connection_error(self, mock_create, monkeypatch):
        """Test create_customer retries on APIConnectionError."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_customer = Mock()
        mock_customer.id = "cus_test999"

        mock_create.side_effect = [APIConnectionError("Connection failed"), mock_customer]

        service = StripeService()
        customer_id = service.create_customer(email="test@example.com")

        assert customer_id == "cus_test999"
        assert mock_create.call_count == 2

    @patch("stripe.Customer.create")
    def test_create_customer_fails_after_max_retries(self, mock_create, monkeypatch):
        """Test create_customer fails after 3 retry attempts."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_create.side_effect = RateLimitError("Rate limit")

        service = StripeService()
        with pytest.raises(RetryError):
            service.create_customer(email="test@example.com")

        assert mock_create.call_count == 3


class TestStripeServiceCreateCheckoutSession:
    """Test StripeService.create_checkout_session method."""

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_success(self, mock_create, monkeypatch):
        """Test creating checkout session successfully."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_session = Mock()
        mock_session.id = "cs_test123"
        mock_session.url = "https://checkout.stripe.com/c/pay/cs_test123"
        mock_create.return_value = mock_session

        service = StripeService()
        session_id, checkout_url = service.create_checkout_session(
            customer_id="cus_test123",
            price_id="price_test_monthly",
            success_url="http://localhost/success",
            cancel_url="http://localhost/cancel",
        )

        assert session_id == "cs_test123"
        assert checkout_url == "https://checkout.stripe.com/c/pay/cs_test123"
        mock_create.assert_called_once_with(
            customer="cus_test123",
            line_items=[{"price": "price_test_monthly", "quantity": 1}],
            mode="subscription",
            success_url="http://localhost/success",
            cancel_url="http://localhost/cancel",
        )

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_retries_on_error(self, mock_create, monkeypatch):
        """Test checkout session creation retries on transient errors."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_session = Mock()
        mock_session.id = "cs_test456"
        mock_session.url = "https://checkout.stripe.com/c/pay/cs_test456"

        mock_create.side_effect = [APIConnectionError("Connection failed"), mock_session]

        service = StripeService()
        session_id, checkout_url = service.create_checkout_session(
            customer_id="cus_test123",
            price_id="price_test_monthly",
            success_url="http://localhost/success",
            cancel_url="http://localhost/cancel",
        )

        assert session_id == "cs_test456"
        assert mock_create.call_count == 2


class TestStripeServiceCreatePortalSession:
    """Test StripeService.create_portal_session method."""

    @patch("stripe.billing_portal.Session.create")
    def test_create_portal_session_success(self, mock_create, monkeypatch):
        """Test creating portal session successfully."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_session = Mock()
        mock_session.url = "https://billing.stripe.com/p/session_test123"
        mock_create.return_value = mock_session

        service = StripeService()
        portal_url = service.create_portal_session(customer_id="cus_test123", return_url="http://localhost/billing")

        assert portal_url == "https://billing.stripe.com/p/session_test123"
        mock_create.assert_called_once_with(customer="cus_test123", return_url="http://localhost/billing")

    @patch("stripe.billing_portal.Session.create")
    def test_create_portal_session_retries_on_error(self, mock_create, monkeypatch):
        """Test portal session creation retries on transient errors."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_session = Mock()
        mock_session.url = "https://billing.stripe.com/p/session_test456"

        mock_create.side_effect = [RateLimitError("Rate limit"), mock_session]

        service = StripeService()
        portal_url = service.create_portal_session(customer_id="cus_test123", return_url="http://localhost/billing")

        assert portal_url == "https://billing.stripe.com/p/session_test456"
        assert mock_create.call_count == 2


class TestStripeServiceGetSubscription:
    """Test StripeService.get_subscription method."""

    @patch("stripe.Subscription.retrieve")
    def test_get_subscription_success(self, mock_retrieve, monkeypatch):
        """Test retrieving subscription successfully."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.status = "active"
        mock_retrieve.return_value = mock_subscription

        service = StripeService()
        subscription = service.get_subscription(subscription_id="sub_test123")

        assert subscription.id == "sub_test123"
        assert subscription.status == "active"
        mock_retrieve.assert_called_once_with("sub_test123")

    @patch("stripe.Subscription.retrieve")
    def test_get_subscription_retries_on_error(self, mock_retrieve, monkeypatch):
        """Test get_subscription retries on transient errors."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_subscription = Mock()
        mock_subscription.id = "sub_test456"

        mock_retrieve.side_effect = [APIConnectionError("Connection failed"), mock_subscription]

        service = StripeService()
        subscription = service.get_subscription(subscription_id="sub_test456")

        assert subscription.id == "sub_test456"
        assert mock_retrieve.call_count == 2


class TestStripeServiceCancelSubscription:
    """Test StripeService.cancel_subscription method."""

    @patch("stripe.Subscription.modify")
    def test_cancel_subscription_at_period_end(self, mock_modify, monkeypatch):
        """Test canceling subscription at period end (default behavior)."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.cancel_at_period_end = True
        mock_modify.return_value = mock_subscription

        service = StripeService()
        subscription = service.cancel_subscription(subscription_id="sub_test123")

        assert subscription.cancel_at_period_end is True
        mock_modify.assert_called_once_with("sub_test123", cancel_at_period_end=True)

    @patch("stripe.Subscription.modify")
    def test_cancel_subscription_at_period_end_explicit(self, mock_modify, monkeypatch):
        """Test canceling subscription at period end with explicit parameter."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_subscription = Mock()
        mock_subscription.cancel_at_period_end = True
        mock_modify.return_value = mock_subscription

        service = StripeService()
        subscription = service.cancel_subscription(subscription_id="sub_test123", at_period_end=True)

        assert subscription.cancel_at_period_end is True
        mock_modify.assert_called_once_with("sub_test123", cancel_at_period_end=True)

    @patch("stripe.Subscription.cancel")
    def test_cancel_subscription_immediately(self, mock_cancel, monkeypatch):
        """Test canceling subscription immediately."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.status = "canceled"
        mock_cancel.return_value = mock_subscription

        service = StripeService()
        subscription = service.cancel_subscription(subscription_id="sub_test123", at_period_end=False)

        assert subscription.status == "canceled"
        mock_cancel.assert_called_once_with("sub_test123")

    @patch("stripe.Subscription.modify")
    def test_cancel_subscription_retries_on_error(self, mock_modify, monkeypatch):
        """Test cancel_subscription retries on transient errors."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        mock_subscription = Mock()
        mock_subscription.cancel_at_period_end = True

        mock_modify.side_effect = [RateLimitError("Rate limit"), mock_subscription]

        service = StripeService()
        subscription = service.cancel_subscription(subscription_id="sub_test123")

        assert subscription.cancel_at_period_end is True
        assert mock_modify.call_count == 2


class TestStripeServiceConstructWebhookEvent:
    """Test StripeService.construct_webhook_event method."""

    @patch("stripe.Webhook.construct_event")
    def test_construct_webhook_event_success(self, mock_construct, monkeypatch):
        """Test constructing webhook event with valid signature."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")

        mock_event = Mock()
        mock_event.id = "evt_test123"
        mock_event.type = "customer.subscription.created"
        mock_construct.return_value = mock_event

        service = StripeService()
        event = service.construct_webhook_event(payload=b"test_payload", signature="valid_signature")

        assert event.id == "evt_test123"
        assert event.type == "customer.subscription.created"
        mock_construct.assert_called_once_with(b"test_payload", "valid_signature", "whsec_test_secret")

    @patch("stripe.Webhook.construct_event")
    def test_construct_webhook_event_invalid_signature(self, mock_construct, monkeypatch):
        """Test constructing webhook event with invalid signature raises error."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")

        mock_construct.side_effect = SignatureVerificationError("Invalid signature", "sig_header")

        service = StripeService()
        with pytest.raises(SignatureVerificationError):
            service.construct_webhook_event(payload=b"test_payload", signature="invalid_signature")

    def test_construct_webhook_event_without_secret_raises_error(self, monkeypatch):
        """Test constructing webhook event without STRIPE_WEBHOOK_SECRET raises ValueError."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

        service = StripeService()
        with pytest.raises(ValueError, match="STRIPE_WEBHOOK_SECRET environment variable is required"):
            service.construct_webhook_event(payload=b"test_payload", signature="test_signature")

    def test_construct_webhook_event_with_empty_secret_raises_error(self, monkeypatch):
        """Test constructing webhook event with empty STRIPE_WEBHOOK_SECRET raises ValueError."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "")

        service = StripeService()
        with pytest.raises(ValueError, match="STRIPE_WEBHOOK_SECRET environment variable is required"):
            service.construct_webhook_event(payload=b"test_payload", signature="test_signature")


class TestStripeServiceGetPriceId:
    """Test StripeService.get_price_id method."""

    def test_get_price_id_for_monthly_plan(self, monkeypatch):
        """Test getting price ID for monthly plan."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        monkeypatch.setenv("STRIPE_PRICE_ID_MONTHLY", "price_test_monthly_123")

        service = StripeService()
        price_id = service.get_price_id(plan_interval="month")

        assert price_id == "price_test_monthly_123"

    def test_get_price_id_for_annual_plan(self, monkeypatch):
        """Test getting price ID for annual plan."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        monkeypatch.setenv("STRIPE_PRICE_ID_ANNUAL", "price_test_annual_456")

        service = StripeService()
        price_id = service.get_price_id(plan_interval="year")

        assert price_id == "price_test_annual_456"

    def test_get_price_id_invalid_interval_raises_error(self, monkeypatch):
        """Test getting price ID with invalid interval raises ValueError."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")

        service = StripeService()
        with pytest.raises(ValueError, match="Invalid plan_interval: week. Must be 'month' or 'year'"):
            service.get_price_id(plan_interval="week")

    def test_get_price_id_monthly_not_configured_raises_error(self, monkeypatch):
        """Test getting monthly price ID without configuration raises ValueError."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        monkeypatch.delenv("STRIPE_PRICE_ID_MONTHLY", raising=False)

        service = StripeService()
        with pytest.raises(ValueError, match="STRIPE_PRICE_ID_MONTHLY environment variable is required"):
            service.get_price_id(plan_interval="month")

    def test_get_price_id_annual_not_configured_raises_error(self, monkeypatch):
        """Test getting annual price ID without configuration raises ValueError."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        monkeypatch.delenv("STRIPE_PRICE_ID_ANNUAL", raising=False)

        service = StripeService()
        with pytest.raises(ValueError, match="STRIPE_PRICE_ID_ANNUAL environment variable is required"):
            service.get_price_id(plan_interval="year")

    def test_get_price_id_with_empty_monthly_price_raises_error(self, monkeypatch):
        """Test getting monthly price ID with empty env var raises ValueError."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        monkeypatch.setenv("STRIPE_PRICE_ID_MONTHLY", "")

        service = StripeService()
        with pytest.raises(ValueError, match="STRIPE_PRICE_ID_MONTHLY environment variable is required"):
            service.get_price_id(plan_interval="month")

    def test_get_price_id_with_empty_annual_price_raises_error(self, monkeypatch):
        """Test getting annual price ID with empty env var raises ValueError."""
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
        monkeypatch.setenv("STRIPE_PRICE_ID_ANNUAL", "")

        service = StripeService()
        with pytest.raises(ValueError, match="STRIPE_PRICE_ID_ANNUAL environment variable is required"):
            service.get_price_id(plan_interval="year")
