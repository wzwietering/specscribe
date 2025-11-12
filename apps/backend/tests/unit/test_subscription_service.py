"""Unit tests for SubscriptionService."""

import logging
import os
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from specscribe.core.database_models import PaymentEventTable, SubscriptionTable, UserTable
from specscribe.core.services.stripe_service import StripeService
from specscribe.core.services.subscription_service import SubscriptionService
from specscribe.core.storage import DatabaseManager

logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def test_db():
    """Create a temporary database for testing."""
    db_path = Path(f"test_{int(time.time() * 1000)}_{threading.get_ident()}_{uuid.uuid4().hex[:8]}.db")
    original_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    db_manager = DatabaseManager(db_path=str(db_path))

    yield str(db_path)

    try:
        if hasattr(db_manager, "engine") and db_manager.engine:
            db_manager.engine.dispose()
    except Exception as e:
        logger.debug(f"Failed to dispose database engine for {db_path}: {e}")

    try:
        if db_path.exists():
            db_path.unlink()
    except Exception as e:
        logger.debug(f"Failed to delete test database file {db_path}: {e}")

    if original_db_url is not None:
        os.environ["DATABASE_URL"] = original_db_url
    elif "DATABASE_URL" in os.environ:
        del os.environ["DATABASE_URL"]


@pytest.fixture(scope="function")
def mock_storage(test_db):
    """Create mock DatabaseManager."""
    return DatabaseManager(db_path=test_db)


@pytest.fixture
def mock_stripe_service():
    """Create mock StripeService."""
    return Mock(spec=StripeService)


@pytest.fixture
def subscription_service(mock_storage, mock_stripe_service):
    """Create SubscriptionService instance with mocked dependencies."""
    return SubscriptionService(storage=mock_storage, stripe_service=mock_stripe_service)


@pytest.fixture
def test_user(test_db):
    """Create a test user in the database."""
    db_manager = DatabaseManager(db_path=test_db)
    with db_manager.SessionLocal() as session:
        user = UserTable(
            id="test-user-123",
            email="test@example.com",
            name="Test User",
            provider="google",
            provider_id="provider-123",
            tier="free",
        )
        session.add(user)
        session.commit()
        return user.id


@pytest.fixture
def test_user_with_customer(test_db):
    """Create a test user with Stripe customer ID."""
    db_manager = DatabaseManager(db_path=test_db)
    with db_manager.SessionLocal() as session:
        user = UserTable(
            id="test-user-456",
            email="customer@example.com",
            name="Customer User",
            provider="google",
            provider_id="provider-456",
            tier="free",
            stripe_customer_id="cus_test123",
        )
        session.add(user)
        session.commit()
        return user.id, "cus_test123"


@pytest.fixture
def mock_stripe_subscription():
    """Create a mock Stripe subscription object."""
    subscription = Mock()
    subscription.id = "sub_test123"
    subscription.customer = "cus_test123"
    subscription.status = "active"
    subscription.current_period_start = 1704067200  # 2024-01-01 00:00:00 UTC
    subscription.current_period_end = 1706745600  # 2024-02-01 00:00:00 UTC
    subscription.cancel_at_period_end = False
    subscription.items = Mock()
    subscription.items.data = [Mock()]
    subscription.items.data[0].price = Mock()
    subscription.items.data[0].price.recurring = Mock()
    subscription.items.data[0].price.recurring.interval = "month"
    return subscription


class TestSubscriptionServiceInitiateCheckout:
    """Test SubscriptionService.initiate_checkout method."""

    def test_initiate_checkout_creates_customer_for_new_user(
        self, subscription_service, test_user, mock_stripe_service
    ):
        """Test checkout creates Stripe customer for user without one."""
        mock_stripe_service.create_customer.return_value = "cus_new123"
        mock_stripe_service.get_price_id.return_value = "price_monthly"
        mock_stripe_service.create_checkout_session.return_value = ("cs_123", "https://checkout.stripe.com/cs_123")

        session_id, checkout_url = subscription_service.initiate_checkout(
            user_id=test_user, plan_interval="month", success_url="http://success", cancel_url="http://cancel"
        )

        assert session_id == "cs_123"
        assert checkout_url == "https://checkout.stripe.com/cs_123"
        mock_stripe_service.create_customer.assert_called_once_with(
            email="test@example.com", name="Test User", metadata={"user_id": test_user}
        )
        mock_stripe_service.get_price_id.assert_called_once_with("month")
        mock_stripe_service.create_checkout_session.assert_called_once_with(
            customer_id="cus_new123", price_id="price_monthly", success_url="http://success", cancel_url="http://cancel"
        )

    def test_initiate_checkout_uses_existing_customer(
        self, subscription_service, test_user_with_customer, mock_stripe_service
    ):
        """Test checkout uses existing Stripe customer."""
        user_id, customer_id = test_user_with_customer
        mock_stripe_service.get_price_id.return_value = "price_annual"
        mock_stripe_service.create_checkout_session.return_value = ("cs_456", "https://checkout.stripe.com/cs_456")

        session_id, checkout_url = subscription_service.initiate_checkout(
            user_id=user_id, plan_interval="year", success_url="http://success", cancel_url="http://cancel"
        )

        assert session_id == "cs_456"
        mock_stripe_service.create_customer.assert_not_called()
        mock_stripe_service.get_price_id.assert_called_once_with("year")
        mock_stripe_service.create_checkout_session.assert_called_once_with(
            customer_id=customer_id,
            price_id="price_annual",
            success_url="http://success",
            cancel_url="http://cancel",
        )

    def test_initiate_checkout_with_nonexistent_user_raises_error(self, subscription_service, mock_stripe_service):
        """Test checkout with nonexistent user raises ValueError."""
        with pytest.raises(ValueError, match="User nonexistent not found"):
            subscription_service.initiate_checkout(
                user_id="nonexistent", plan_interval="month", success_url="http://success", cancel_url="http://cancel"
            )


class TestSubscriptionServiceCreatePortalSession:
    """Test SubscriptionService.create_portal_session method."""

    def test_create_portal_session_success(self, subscription_service, test_user_with_customer, mock_stripe_service):
        """Test creating portal session for user with customer ID."""
        user_id, customer_id = test_user_with_customer
        mock_stripe_service.create_portal_session.return_value = "https://billing.stripe.com/session123"

        portal_url = subscription_service.create_portal_session(user_id=user_id, return_url="http://billing")

        assert portal_url == "https://billing.stripe.com/session123"
        mock_stripe_service.create_portal_session.assert_called_once_with(customer_id, "http://billing")

    def test_create_portal_session_without_customer_raises_error(
        self, subscription_service, test_user, mock_stripe_service
    ):
        """Test portal session for user without customer raises ValueError."""
        with pytest.raises(ValueError, match=f"User {test_user} has no Stripe customer"):
            subscription_service.create_portal_session(user_id=test_user, return_url="http://billing")

    def test_create_portal_session_with_nonexistent_user_raises_error(self, subscription_service, mock_stripe_service):
        """Test portal session with nonexistent user raises ValueError."""
        with pytest.raises(ValueError, match="User nonexistent not found"):
            subscription_service.create_portal_session(user_id="nonexistent", return_url="http://billing")


class TestSubscriptionServiceGetUserSubscription:
    """Test SubscriptionService.get_user_subscription method."""

    def test_get_user_subscription_returns_subscription(self, subscription_service, test_user_with_customer, test_db):
        """Test getting user subscription when it exists."""
        user_id, customer_id = test_user_with_customer
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            sub = SubscriptionTable(
                user_id=user_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id="sub_test123",
                status="active",
                plan_interval="month",
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC),
                cancel_at_period_end=False,
            )
            session.add(sub)
            session.commit()

        result = subscription_service.get_user_subscription(user_id)
        assert result is not None
        assert result.stripe_subscription_id == "sub_test123"

    def test_get_user_subscription_returns_none_when_not_exists(self, subscription_service, test_user):
        """Test getting user subscription returns None when no subscription."""
        result = subscription_service.get_user_subscription(test_user)
        assert result is None


class TestSubscriptionServiceHandleCheckoutCompleted:
    """Test SubscriptionService.handle_checkout_completed method."""

    def test_handle_checkout_completed_with_string_subscription_id(
        self, subscription_service, test_user_with_customer, test_db, mock_stripe_service, mock_stripe_subscription
    ):
        """Test checkout completed handler with string subscription ID."""
        user_id, customer_id = test_user_with_customer
        mock_stripe_service.get_subscription.return_value = mock_stripe_subscription

        mock_session = Mock()
        mock_session.customer = customer_id
        mock_session.subscription = "sub_test123"

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription_service.handle_checkout_completed(session, mock_session)
            session.commit()

            # Verify subscription was created
            sub = session.query(SubscriptionTable).filter_by(user_id=user_id).first()
            assert sub is not None
            assert sub.stripe_subscription_id == "sub_test123"

    def test_handle_checkout_completed_with_subscription_object(
        self, subscription_service, test_user_with_customer, test_db, mock_stripe_subscription
    ):
        """Test checkout completed handler with Subscription object."""
        user_id, customer_id = test_user_with_customer

        mock_session = Mock()
        mock_session.customer = customer_id
        mock_session.subscription = mock_stripe_subscription

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription_service.handle_checkout_completed(session, mock_session)
            session.commit()

            # Verify subscription was created
            sub = session.query(SubscriptionTable).filter_by(user_id=user_id).first()
            assert sub is not None

    def test_handle_checkout_completed_without_customer_id_returns_early(
        self, subscription_service, test_db, mock_stripe_service
    ):
        """Test checkout completed returns early if customer_id missing."""
        mock_session = Mock()
        mock_session.customer = None
        mock_session.subscription = "sub_test123"

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription_service.handle_checkout_completed(session, mock_session)
            # Should return early, no error
            mock_stripe_service.get_subscription.assert_not_called()

    def test_handle_checkout_completed_without_subscription_id_returns_early(
        self, subscription_service, test_db, mock_stripe_service
    ):
        """Test checkout completed returns early if subscription_id missing."""
        mock_session = Mock()
        mock_session.customer = "cus_test123"
        mock_session.subscription = None

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription_service.handle_checkout_completed(session, mock_session)
            mock_stripe_service.get_subscription.assert_not_called()


class TestSubscriptionServiceHandleSubscriptionCreated:
    """Test SubscriptionService.handle_subscription_created method."""

    def test_handle_subscription_created(
        self, subscription_service, test_user_with_customer, test_db, mock_stripe_subscription
    ):
        """Test subscription created webhook handler."""
        user_id, _ = test_user_with_customer

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription_service.handle_subscription_created(session, mock_stripe_subscription)
            session.commit()

            sub = session.query(SubscriptionTable).filter_by(user_id=user_id).first()
            assert sub is not None
            assert sub.status == "active"


class TestSubscriptionServiceHandleSubscriptionUpdated:
    """Test SubscriptionService.handle_subscription_updated method."""

    def test_handle_subscription_updated(
        self, subscription_service, test_user_with_customer, test_db, mock_stripe_subscription
    ):
        """Test subscription updated webhook handler."""
        user_id, customer_id = test_user_with_customer

        # Create existing subscription
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            sub = SubscriptionTable(
                user_id=user_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id="sub_test123",
                status="active",
                plan_interval="month",
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC),
                cancel_at_period_end=False,
            )
            session.add(sub)
            session.commit()

        # Update subscription status
        mock_stripe_subscription.status = "past_due"

        with db_manager.SessionLocal() as session:
            subscription_service.handle_subscription_updated(session, mock_stripe_subscription)
            session.commit()

            sub = session.query(SubscriptionTable).filter_by(user_id=user_id).first()
            assert sub.status == "past_due"


class TestSubscriptionServiceHandleSubscriptionDeleted:
    """Test SubscriptionService.handle_subscription_deleted method."""

    def test_handle_subscription_deleted_downgrades_user(
        self, subscription_service, test_user_with_customer, test_db, mock_stripe_subscription
    ):
        """Test subscription deleted downgrades user to free tier."""
        user_id, customer_id = test_user_with_customer

        # Upgrade user to pro first
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.get(UserTable, user_id)
            user.tier = "pro"
            sub = SubscriptionTable(
                user_id=user_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id="sub_test123",
                status="active",
                plan_interval="month",
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC),
                cancel_at_period_end=False,
            )
            session.add(sub)
            session.commit()

        with db_manager.SessionLocal() as session:
            subscription_service.handle_subscription_deleted(session, mock_stripe_subscription)
            session.commit()

            user = session.get(UserTable, user_id)
            assert user.tier == "free"

            sub = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_test123").first()
            assert sub.status == "canceled"

    def test_handle_subscription_deleted_without_user_returns_early(
        self, subscription_service, test_db, mock_stripe_subscription
    ):
        """Test subscription deleted returns early if user not found."""
        mock_stripe_subscription.customer = "cus_nonexistent"

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription_service.handle_subscription_deleted(session, mock_stripe_subscription)
            # Should return early without error


class TestSubscriptionServiceDeterminePlanInterval:
    """Test SubscriptionService._determine_plan_interval method."""

    def test_determine_plan_interval_monthly(self, subscription_service):
        """Test determining plan interval for monthly subscription."""
        mock_sub = Mock()
        mock_sub.items = Mock()
        mock_sub.items.data = [Mock()]
        mock_sub.items.data[0].price = Mock()
        mock_sub.items.data[0].price.recurring = Mock()
        mock_sub.items.data[0].price.recurring.interval = "month"

        result = subscription_service._determine_plan_interval(mock_sub)
        assert result == "month"

    def test_determine_plan_interval_annual(self, subscription_service):
        """Test determining plan interval for annual subscription."""
        mock_sub = Mock()
        mock_sub.items = Mock()
        mock_sub.items.data = [Mock()]
        mock_sub.items.data[0].price = Mock()
        mock_sub.items.data[0].price.recurring = Mock()
        mock_sub.items.data[0].price.recurring.interval = "year"

        result = subscription_service._determine_plan_interval(mock_sub)
        assert result == "year"

    def test_determine_plan_interval_defaults_to_month(self, subscription_service):
        """Test plan interval defaults to month when not specified."""
        mock_sub = Mock()
        mock_sub.items = None

        result = subscription_service._determine_plan_interval(mock_sub)
        assert result == "month"


class TestSubscriptionServiceExtractSubscriptionTimestamps:
    """Test SubscriptionService._extract_subscription_timestamps method."""

    def test_extract_timestamps_success(self, subscription_service):
        """Test extracting valid timestamps."""
        mock_sub = Mock()
        mock_sub.current_period_start = 1704067200
        mock_sub.current_period_end = 1706745600

        result = subscription_service._extract_subscription_timestamps(mock_sub)
        assert result == (1704067200, 1706745600)

    def test_extract_timestamps_returns_none_for_invalid_start(self, subscription_service):
        """Test returns None if start timestamp is invalid."""
        mock_sub = Mock()
        mock_sub.current_period_start = "invalid"
        mock_sub.current_period_end = 1706745600

        result = subscription_service._extract_subscription_timestamps(mock_sub)
        assert result is None

    def test_extract_timestamps_returns_none_for_missing_timestamps(self, subscription_service):
        """Test returns None if timestamps are missing."""
        mock_sub = Mock(spec=[])

        result = subscription_service._extract_subscription_timestamps(mock_sub)
        assert result is None


class TestSubscriptionServiceUpdateSubscriptionRecord:
    """Test SubscriptionService._update_subscription_record method."""

    def test_update_subscription_record(self, subscription_service, test_db, test_user_with_customer):
        """Test updating subscription record."""
        user_id, customer_id = test_user_with_customer
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            sub = SubscriptionTable(
                user_id=user_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id="sub_test123",
                status="active",
                plan_interval="month",
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC),
                cancel_at_period_end=False,
            )
            session.add(sub)
            session.commit()

            mock_stripe_sub = Mock()
            mock_stripe_sub.status = "past_due"
            mock_stripe_sub.cancel_at_period_end = True

            subscription_service._update_subscription_record(sub, mock_stripe_sub, "year", (1704067200, 1706745600))
            session.commit()

            updated_sub = session.get(SubscriptionTable, sub.id)
            assert updated_sub.status == "past_due"
            assert updated_sub.plan_interval == "year"
            assert updated_sub.cancel_at_period_end is True


class TestSubscriptionServiceCreateSubscriptionRecord:
    """Test SubscriptionService._create_subscription_record method."""

    def test_create_subscription_record(self, subscription_service, test_db, test_user_with_customer):
        """Test creating subscription record."""
        user_id, customer_id = test_user_with_customer
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.get(UserTable, user_id)

            mock_stripe_sub = Mock()
            mock_stripe_sub.id = "sub_new123"
            mock_stripe_sub.customer = customer_id
            mock_stripe_sub.status = "active"
            mock_stripe_sub.cancel_at_period_end = False

            new_record = subscription_service._create_subscription_record(
                user, mock_stripe_sub, "month", (1704067200, 1706745600)
            )

            assert new_record.user_id == user_id
            assert new_record.stripe_subscription_id == "sub_new123"
            assert new_record.status == "active"
            assert new_record.plan_interval == "month"


class TestSubscriptionServiceUpdateUserTier:
    """Test SubscriptionService._update_user_tier method."""

    def test_update_user_tier_upgrades_to_pro_for_active(self, subscription_service, test_db, test_user):
        """Test user tier upgraded to pro for active subscription."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.get(UserTable, test_user)

            mock_sub = Mock()
            mock_sub.id = "sub_test123"
            mock_sub.status = "active"

            subscription_service._update_user_tier(user, mock_sub)
            session.commit()

            assert user.tier == "pro"

    def test_update_user_tier_upgrades_to_pro_for_trialing(self, subscription_service, test_db, test_user):
        """Test user tier upgraded to pro for trialing subscription."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.get(UserTable, test_user)

            mock_sub = Mock()
            mock_sub.id = "sub_test123"
            mock_sub.status = "trialing"

            subscription_service._update_user_tier(user, mock_sub)
            session.commit()

            assert user.tier == "pro"

    def test_update_user_tier_keeps_tier_for_past_due(self, subscription_service, test_db, test_user):
        """Test user tier unchanged for past_due subscription."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.get(UserTable, test_user)
            user.tier = "free"

            mock_sub = Mock()
            mock_sub.id = "sub_test123"
            mock_sub.status = "past_due"

            subscription_service._update_user_tier(user, mock_sub)
            session.commit()

            assert user.tier == "free"


class TestSubscriptionServiceUpsertSubscription:
    """Test SubscriptionService._upsert_subscription method."""

    def test_upsert_creates_new_subscription(
        self, subscription_service, test_user_with_customer, test_db, mock_stripe_subscription
    ):
        """Test upsert creates new subscription when it doesn't exist."""
        user_id, _ = test_user_with_customer
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription_service._upsert_subscription(session, mock_stripe_subscription)
            session.commit()

            sub = session.query(SubscriptionTable).filter_by(user_id=user_id).first()
            assert sub is not None
            assert sub.stripe_subscription_id == "sub_test123"
            assert sub.status == "active"

    def test_upsert_updates_existing_subscription(
        self, subscription_service, test_user_with_customer, test_db, mock_stripe_subscription
    ):
        """Test upsert updates existing subscription."""
        user_id, customer_id = test_user_with_customer
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            # Create existing subscription
            sub = SubscriptionTable(
                user_id=user_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id="sub_test123",
                status="active",
                plan_interval="month",
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC),
                cancel_at_period_end=False,
            )
            session.add(sub)
            session.commit()

            # Update with new status
            mock_stripe_subscription.status = "canceled"
            subscription_service._upsert_subscription(session, mock_stripe_subscription)
            session.commit()

            updated_sub = session.query(SubscriptionTable).filter_by(user_id=user_id).first()
            assert updated_sub.status == "canceled"

    def test_upsert_returns_early_if_user_not_found(self, subscription_service, test_db, mock_stripe_subscription):
        """Test upsert returns early if user not found by customer_id."""
        mock_stripe_subscription.customer = "cus_nonexistent"
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription_service._upsert_subscription(session, mock_stripe_subscription)
            # Should return early without error

    def test_upsert_returns_early_if_timestamps_invalid(self, subscription_service, test_user_with_customer, test_db):
        """Test upsert returns early if timestamps are invalid."""
        _, customer_id = test_user_with_customer
        mock_sub = Mock()
        mock_sub.id = "sub_test123"
        mock_sub.customer = customer_id
        mock_sub.status = "active"
        mock_sub.current_period_start = "invalid"
        mock_sub.current_period_end = 1706745600
        # Properly mock items.data structure
        mock_sub.items = Mock()
        mock_sub.items.data = [Mock()]
        mock_sub.items.data[0].price = Mock()
        mock_sub.items.data[0].price.recurring = Mock()
        mock_sub.items.data[0].price.recurring.interval = "month"

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription_service._upsert_subscription(session, mock_sub)
            # Should return early without creating subscription


class TestSubscriptionServiceLogWebhookEvent:
    """Test SubscriptionService.log_webhook_event method."""

    def test_log_webhook_event(self, subscription_service, test_db, test_user):
        """Test logging webhook event."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription_service.log_webhook_event(
                session,
                event_type="customer.subscription.created",
                stripe_event_id="evt_test123",
                status="processed",
                user_id=test_user,
            )
            session.commit()

            event = session.query(PaymentEventTable).filter_by(stripe_event_id="evt_test123").first()
            assert event is not None
            assert event.event_type == "customer.subscription.created"
            assert event.status == "processed"
            assert event.user_id == test_user

    def test_log_webhook_event_without_user_id(self, subscription_service, test_db):
        """Test logging webhook event without user_id."""
        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription_service.log_webhook_event(
                session, event_type="unknown.event", stripe_event_id="evt_test456", status="failed", user_id=None
            )
            session.commit()

            event = session.query(PaymentEventTable).filter_by(stripe_event_id="evt_test456").first()
            assert event is not None
            assert event.user_id is None
