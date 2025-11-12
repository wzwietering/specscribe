"""API integration tests for Stripe webhook endpoint."""

import json
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
import stripe
from fastapi import status

from specscribe.core.database_models import PaymentEventTable, SubscriptionTable, UserTable
from specscribe.core.storage import DatabaseManager


@pytest.fixture
def mock_webhook_signature():
    """Mock webhook signature for testing."""
    return "t=1234567890,v1=mock_signature_hash"


@pytest.fixture
def mock_stripe_constructs():
    """Mock Stripe construct_from methods."""
    with (
        patch("stripe.checkout.Session.construct_from") as mock_session,
        patch("stripe.Subscription.construct_from") as mock_subscription,
    ):
        yield mock_session, mock_subscription


@pytest.fixture
def webhook_payload_checkout_completed():
    """Webhook payload for checkout.session.completed event."""
    return {
        "id": "evt_checkout_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test123",
                "customer": "cus_test123",
                "subscription": "sub_test123",
                "mode": "subscription",
            }
        },
    }


@pytest.fixture
def webhook_payload_subscription_created():
    """Webhook payload for customer.subscription.created event."""
    return {
        "id": "evt_sub_created_123",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_test123",
                "customer": "cus_test123",
                "status": "active",
                "current_period_start": 1704067200,  # 2024-01-01
                "current_period_end": 1706745600,  # 2024-02-01
                "cancel_at_period_end": False,
                "items": {"data": [{"price": {"recurring": {"interval": "month"}}}]},
            }
        },
    }


@pytest.fixture
def webhook_payload_subscription_updated():
    """Webhook payload for customer.subscription.updated event."""
    return {
        "id": "evt_sub_updated_123",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test123",
                "customer": "cus_test123",
                "status": "past_due",
                "current_period_start": 1704067200,
                "current_period_end": 1706745600,
                "cancel_at_period_end": False,
                "items": {"data": [{"price": {"recurring": {"interval": "month"}}}]},
            }
        },
    }


@pytest.fixture
def webhook_payload_subscription_deleted():
    """Webhook payload for customer.subscription.deleted event."""
    return {
        "id": "evt_sub_deleted_123",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_test123",
                "customer": "cus_test123",
                "status": "canceled",
                "current_period_start": 1704067200,
                "current_period_end": 1706745600,
                "cancel_at_period_end": False,
                "items": {"data": [{"price": {"recurring": {"interval": "month"}}}]},
            }
        },
    }


# ============================================================================
# Webhook Signature Verification Tests
# ============================================================================


class TestWebhookSignatureVerification:
    """Test webhook signature verification."""

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_rejects_invalid_signature(self, mock_get_service, client, webhook_payload_checkout_completed):
        """Test webhook rejects invalid signature."""
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.construct_webhook_event.side_effect = stripe.SignatureVerificationError(
            "Invalid signature", "sig_header"
        )

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_checkout_completed),
            headers={"stripe-signature": "invalid_signature"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "Invalid signature" in response.json()["detail"]

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_rejects_invalid_payload(self, mock_get_service, client):
        """Test webhook rejects malformed payload."""
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.construct_webhook_event.side_effect = ValueError("Invalid JSON")

        response = client.post(
            "/api/v1/billing/webhook",
            content="invalid json",
            headers={"stripe-signature": "sig_header"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid payload" in response.json()["detail"]

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_requires_signature_header(self, mock_get_service, client, webhook_payload_checkout_completed):
        """Test webhook requires stripe-signature header."""
        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_checkout_completed),
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ============================================================================
# Checkout Session Completed Event Tests
# ============================================================================


class TestCheckoutSessionCompletedEvent:
    """Test checkout.session.completed webhook event."""

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_processes_checkout_completed_successfully(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_checkout_completed,
        mock_webhook_signature,
        mock_stripe_constructs,
    ):
        """Test successful processing of checkout.session.completed event."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        # Set up user with customer ID
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        # Mock Stripe service
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        # Create mock event
        mock_event = Mock()
        mock_event.id = "evt_checkout_123"
        mock_event.type = "checkout.session.completed"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_checkout_completed["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        # Mock checkout session construct
        mock_session = Mock()
        mock_session.customer = "cus_test123"
        mock_session.subscription = "sub_test123"
        mock_construct_session.return_value = mock_session

        # Mock subscription retrieval
        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.customer = "cus_test123"
        mock_subscription.status = "active"
        mock_subscription.current_period_start = 1704067200
        mock_subscription.current_period_end = 1706745600
        mock_subscription.cancel_at_period_end = False
        mock_subscription.items = Mock()
        mock_subscription.items.data = [Mock()]
        mock_subscription.items.data[0].price = Mock()
        mock_subscription.items.data[0].price.recurring = Mock()
        mock_subscription.items.data[0].price.recurring.interval = "month"
        mock_service.get_subscription.return_value = mock_subscription

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_checkout_completed),
            headers={"stripe-signature": mock_webhook_signature},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "success"}

        # Verify subscription was created
        with db_manager.SessionLocal() as session:
            subscription = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_test123").first()
            assert subscription is not None
            assert subscription.status == "active"
            assert subscription.plan_interval == "month"

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_upgrades_user_tier_to_pro(
        self, mock_get_service, client, test_db, webhook_payload_checkout_completed, mock_webhook_signature
    ):
        """Test checkout completed upgrades user tier to pro."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            user.tier = "free"
            session.commit()
            user_id = user.id

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_checkout_123"
        mock_event.type = "checkout.session.completed"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_checkout_completed["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.customer = "cus_test123"
        mock_subscription.status = "active"
        mock_subscription.current_period_start = 1704067200
        mock_subscription.current_period_end = 1706745600
        mock_subscription.cancel_at_period_end = False
        mock_subscription.items = Mock()
        mock_subscription.items.data = [Mock()]
        mock_subscription.items.data[0].price = Mock()
        mock_subscription.items.data[0].price.recurring = Mock()
        mock_subscription.items.data[0].price.recurring.interval = "month"
        mock_service.get_subscription.return_value = mock_subscription

        client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_checkout_completed),
            headers={"stripe-signature": mock_webhook_signature},
        )

        # Verify user tier upgraded
        with db_manager.SessionLocal() as session:
            user = session.get(UserTable, user_id)
            assert user.tier == "pro"


# ============================================================================
# Subscription Created Event Tests
# ============================================================================


class TestSubscriptionCreatedEvent:
    """Test customer.subscription.created webhook event."""

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_processes_subscription_created_successfully(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_subscription_created,
        mock_webhook_signature,
        mock_stripe_constructs,
    ):
        """Test successful processing of subscription.created event."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_sub_created_123"
        mock_event.type = "customer.subscription.created"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_subscription_created["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        # Mock the subscription construct_from
        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.customer = "cus_test123"
        mock_subscription.status = "active"
        mock_subscription.current_period_start = 1704067200
        mock_subscription.current_period_end = 1706745600
        mock_subscription.cancel_at_period_end = False
        mock_subscription.items = Mock()
        mock_subscription.items.data = [Mock()]
        mock_subscription.items.data[0].price = Mock()
        mock_subscription.items.data[0].price.recurring = Mock()
        mock_subscription.items.data[0].price.recurring.interval = "month"
        mock_construct_subscription.return_value = mock_subscription

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_subscription_created),
            headers={"stripe-signature": mock_webhook_signature},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify subscription created
        with db_manager.SessionLocal() as session:
            subscription = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_test123").first()
            assert subscription is not None
            assert subscription.status == "active"

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_creates_subscription_for_annual_plan(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_subscription_created,
        mock_webhook_signature,
        mock_stripe_constructs,
    ):
        """Test subscription created handles annual plan."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        # Modify payload for annual plan
        webhook_payload_subscription_created["data"]["object"]["items"]["data"][0]["price"]["recurring"]["interval"] = (
            "year"
        )

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_sub_created_123"
        mock_event.type = "customer.subscription.created"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_subscription_created["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        # Mock subscription construct_from for annual plan
        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.customer = "cus_test123"
        mock_subscription.status = "active"
        mock_subscription.current_period_start = 1704067200
        mock_subscription.current_period_end = 1706745600
        mock_subscription.cancel_at_period_end = False
        mock_subscription.items = Mock()
        mock_subscription.items.data = [Mock()]
        mock_subscription.items.data[0].price = Mock()
        mock_subscription.items.data[0].price.recurring = Mock()
        mock_subscription.items.data[0].price.recurring.interval = "year"
        mock_construct_subscription.return_value = mock_subscription

        client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_subscription_created),
            headers={"stripe-signature": mock_webhook_signature},
        )

        # Verify annual subscription
        with db_manager.SessionLocal() as session:
            subscription = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_test123").first()
            assert subscription.plan_interval == "year"


# ============================================================================
# Subscription Updated Event Tests
# ============================================================================


class TestSubscriptionUpdatedEvent:
    """Test customer.subscription.updated webhook event."""

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_processes_subscription_updated_successfully(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_subscription_updated,
        mock_webhook_signature,
        mock_stripe_constructs,
    ):
        """Test successful processing of subscription.updated event."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            # Create existing subscription
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

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_sub_updated_123"
        mock_event.type = "customer.subscription.updated"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_subscription_updated["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        # Mock subscription construct_from
        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.customer = "cus_test123"
        mock_subscription.status = "past_due"
        mock_subscription.current_period_start = 1704067200
        mock_subscription.current_period_end = 1706745600
        mock_subscription.cancel_at_period_end = False
        mock_subscription.items = Mock()
        mock_subscription.items.data = [Mock()]
        mock_subscription.items.data[0].price = Mock()
        mock_subscription.items.data[0].price.recurring = Mock()
        mock_subscription.items.data[0].price.recurring.interval = "month"
        mock_construct_subscription.return_value = mock_subscription

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_subscription_updated),
            headers={"stripe-signature": mock_webhook_signature},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify subscription updated to past_due
        with db_manager.SessionLocal() as session:
            subscription = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_test123").first()
            assert subscription.status == "past_due"

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_maintains_pro_tier_for_past_due_status(
        self, mock_get_service, client, test_db, webhook_payload_subscription_updated, mock_webhook_signature
    ):
        """Test past_due status doesn't downgrade user tier."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            user.tier = "pro"
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
            user_id = user.id

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_sub_updated_123"
        mock_event.type = "customer.subscription.updated"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_subscription_updated["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_subscription_updated),
            headers={"stripe-signature": mock_webhook_signature},
        )

        # Verify user tier remains pro (past_due doesn't downgrade)
        with db_manager.SessionLocal() as session:
            user = session.get(UserTable, user_id)
            # Past due is not in the "active" or "trialing" status list, so tier should remain unchanged
            assert user.tier == "pro"


# ============================================================================
# Subscription Deleted Event Tests
# ============================================================================


class TestSubscriptionDeletedEvent:
    """Test customer.subscription.deleted webhook event."""

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_processes_subscription_deleted_successfully(
        self, mock_get_service, client, test_db, webhook_payload_subscription_deleted, mock_webhook_signature
    ):
        """Test successful processing of subscription.deleted event."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            user.tier = "pro"
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

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_sub_deleted_123"
        mock_event.type = "customer.subscription.deleted"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_subscription_deleted["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_subscription_deleted),
            headers={"stripe-signature": mock_webhook_signature},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify subscription marked as canceled
        with db_manager.SessionLocal() as session:
            subscription = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_test123").first()
            assert subscription.status == "canceled"

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_downgrades_user_tier_to_free(
        self, mock_get_service, client, test_db, webhook_payload_subscription_deleted, mock_webhook_signature
    ):
        """Test subscription deleted downgrades user to free tier."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            user.tier = "pro"
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
            user_id = user.id

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_sub_deleted_123"
        mock_event.type = "customer.subscription.deleted"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_subscription_deleted["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_subscription_deleted),
            headers={"stripe-signature": mock_webhook_signature},
        )

        # Verify user downgraded to free
        with db_manager.SessionLocal() as session:
            user = session.get(UserTable, user_id)
            assert user.tier == "free"


# ============================================================================
# Idempotency Tests
# ============================================================================


class TestWebhookIdempotency:
    """Test webhook idempotency (duplicate event handling)."""

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_prevents_duplicate_event_processing(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_checkout_completed,
        mock_webhook_signature,
        mock_stripe_constructs,
    ):
        """Test duplicate events are detected and ignored."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_checkout_123"
        mock_event.type = "checkout.session.completed"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_checkout_completed["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        # Mock checkout session construct
        mock_session = Mock()
        mock_session.customer = "cus_test123"
        mock_session.subscription = "sub_test123"
        mock_construct_session.return_value = mock_session

        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.customer = "cus_test123"
        mock_subscription.status = "active"
        mock_subscription.current_period_start = 1704067200
        mock_subscription.current_period_end = 1706745600
        mock_subscription.cancel_at_period_end = False
        mock_subscription.items = Mock()
        mock_subscription.items.data = [Mock()]
        mock_subscription.items.data[0].price = Mock()
        mock_subscription.items.data[0].price.recurring = Mock()
        mock_subscription.items.data[0].price.recurring.interval = "month"
        mock_service.get_subscription.return_value = mock_subscription

        # First request
        response1 = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_checkout_completed),
            headers={"stripe-signature": mock_webhook_signature},
        )
        assert response1.status_code == status.HTTP_200_OK

        # Duplicate request with same event ID
        response2 = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_checkout_completed),
            headers={"stripe-signature": mock_webhook_signature},
        )
        assert response2.status_code == status.HTTP_200_OK
        # Idempotency check returns success response
        assert response2.json()["status"] == "success"

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_logs_payment_events(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_checkout_completed,
        mock_webhook_signature,
        mock_stripe_constructs,
    ):
        """Test webhook events are logged in payment_events table."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_checkout_123"
        mock_event.type = "checkout.session.completed"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_checkout_completed["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        # Mock checkout session construct
        mock_session = Mock()
        mock_session.customer = "cus_test123"
        mock_session.subscription = "sub_test123"
        mock_construct_session.return_value = mock_session

        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.customer = "cus_test123"
        mock_subscription.status = "active"
        mock_subscription.current_period_start = 1704067200
        mock_subscription.current_period_end = 1706745600
        mock_subscription.cancel_at_period_end = False
        mock_subscription.items = Mock()
        mock_subscription.items.data = [Mock()]
        mock_subscription.items.data[0].price = Mock()
        mock_subscription.items.data[0].price.recurring = Mock()
        mock_subscription.items.data[0].price.recurring.interval = "month"
        mock_service.get_subscription.return_value = mock_subscription

        client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_checkout_completed),
            headers={"stripe-signature": mock_webhook_signature},
        )

        # Verify event logged - only ONE event with "processed" status after fix
        with db_manager.SessionLocal() as session:
            events = session.query(PaymentEventTable).filter_by(stripe_event_id="evt_checkout_123").all()
            assert len(events) == 1  # Single event, status updated from "processing" to "processed"
            assert events[0].status == "processed"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestWebhookErrorHandling:
    """Test webhook error handling."""

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_handles_processing_errors_gracefully(
        self, mock_get_service, client, test_db, webhook_payload_checkout_completed, mock_webhook_signature
    ):
        """Test webhook handles processing errors and logs them."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_checkout_error_123"
        mock_event.type = "checkout.session.completed"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_checkout_completed["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        # Make get_subscription raise an error
        mock_service.get_subscription.side_effect = Exception("Stripe API error")

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_checkout_completed),
            headers={"stripe-signature": mock_webhook_signature},
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Webhook processing failed" in response.json()["detail"]

        # Verify error was logged
        with db_manager.SessionLocal() as session:
            error_event = (
                session.query(PaymentEventTable)
                .filter(
                    PaymentEventTable.stripe_event_id == "evt_checkout_error_123",
                    PaymentEventTable.status.like("failed:%"),
                )
                .first()
            )
            assert error_event is not None
            assert "Stripe API error" in error_event.status

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_ignores_unknown_event_types(
        self, mock_get_service, client, test_db, mock_webhook_signature, mock_stripe_constructs
    ):
        """Test webhook ignores unknown event types gracefully."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        # Create event with unknown type
        unknown_payload = {
            "id": "evt_unknown_123",
            "type": "customer.source.created",  # Unknown event type
            "data": {"object": {"id": "src_test123"}},
        }

        mock_event = Mock()
        mock_event.id = "evt_unknown_123"
        mock_event.type = "customer.source.created"
        mock_event.data = Mock()
        mock_event.data.object = unknown_payload["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(unknown_payload),
            headers={"stripe-signature": mock_webhook_signature},
        )

        # Should succeed (ignore unknown event type)
        assert response.status_code == status.HTTP_200_OK


# ============================================================================
# Integration Tests
# ============================================================================


class TestWebhookEndToEndFlows:
    """Test complete end-to-end webhook flows."""

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_complete_subscription_lifecycle(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_subscription_created,
        webhook_payload_subscription_deleted,
        mock_webhook_signature,
        mock_stripe_constructs,
    ):
        """Test complete subscription lifecycle: create -> delete."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            user.tier = "free"
            session.commit()
            user_id = user.id

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        # Step 1: Create subscription
        mock_event = Mock()
        mock_event.id = "evt_sub_created_123"
        mock_event.type = "customer.subscription.created"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_subscription_created["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        # Mock subscription construct_from for created event
        mock_sub_created = Mock()
        mock_sub_created.id = "sub_test123"
        mock_sub_created.customer = "cus_test123"
        mock_sub_created.status = "active"
        mock_sub_created.current_period_start = 1704067200
        mock_sub_created.current_period_end = 1706745600
        mock_sub_created.cancel_at_period_end = False
        mock_sub_created.items = Mock()
        mock_sub_created.items.data = [Mock()]
        mock_sub_created.items.data[0].price = Mock()
        mock_sub_created.items.data[0].price.recurring = Mock()
        mock_sub_created.items.data[0].price.recurring.interval = "month"
        mock_construct_subscription.return_value = mock_sub_created

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_subscription_created),
            headers={"stripe-signature": mock_webhook_signature},
        )
        assert response.status_code == status.HTTP_200_OK

        # Verify subscription created and user upgraded
        with db_manager.SessionLocal() as session:
            user = session.get(UserTable, user_id)
            assert user.tier == "pro"
            subscription = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_test123").first()
            assert subscription.status == "active"

        # Step 2: Delete subscription
        mock_event = Mock()
        mock_event.id = "evt_sub_deleted_123"
        mock_event.type = "customer.subscription.deleted"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_subscription_deleted["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        # Mock subscription construct_from for deleted event
        mock_sub_deleted = Mock()
        mock_sub_deleted.id = "sub_test123"
        mock_sub_deleted.customer = "cus_test123"
        mock_sub_deleted.status = "canceled"
        mock_sub_deleted.current_period_start = 1704067200
        mock_sub_deleted.current_period_end = 1706745600
        mock_sub_deleted.cancel_at_period_end = False
        mock_sub_deleted.items = Mock()
        mock_sub_deleted.items.data = [Mock()]
        mock_sub_deleted.items.data[0].price = Mock()
        mock_sub_deleted.items.data[0].price.recurring = Mock()
        mock_sub_deleted.items.data[0].price.recurring.interval = "month"
        mock_construct_subscription.return_value = mock_sub_deleted

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_subscription_deleted),
            headers={"stripe-signature": mock_webhook_signature},
        )
        assert response.status_code == status.HTTP_200_OK

        # Verify subscription canceled and user downgraded
        with db_manager.SessionLocal() as session:
            user = session.get(UserTable, user_id)
            assert user.tier == "free"
            subscription = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_test123").first()
            assert subscription.status == "canceled"
