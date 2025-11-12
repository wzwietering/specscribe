"""Shared test fixtures for API tests."""

import logging
import os
import threading
import time
import uuid
from pathlib import Path

# Set up test environment variables before any other imports
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-characters-for-testing")
os.environ.setdefault("ENVIRONMENT", "test")
# Use mock provider for tests to avoid API calls
os.environ.setdefault("MODEL_ID", "mock:test-model")
# Set high quota limit for tests to avoid hitting limits during test runs
os.environ.setdefault("FREE_TIER_QUESTION_LIMIT", "1000")
# Stripe test environment variables
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake_key_for_testing_123456789")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_fake_webhook_secret_123456789")
os.environ.setdefault("STRIPE_PRICE_ID_MONTHLY", "price_test_monthly_123")
os.environ.setdefault("STRIPE_PRICE_ID_ANNUAL", "price_test_annual_123")

from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from specscribe.api.dependencies import get_current_user_id, get_storage
from specscribe.api.main import app
from specscribe.api.middleware import AuthenticationMiddleware
from specscribe.core.models import UserCreate
from specscribe.core.services.user_service import UserService
from specscribe.core.storage import DatabaseManager

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session", autouse=True)
def validate_test_environment():
    """Validate test environment setup."""
    jwt_secret = os.environ.get("JWT_SECRET_KEY")
    if not jwt_secret or len(jwt_secret) < 32:
        pytest.fail("JWT_SECRET_KEY must be at least 32 characters for testing")

    # Ensure we're in test mode
    assert os.environ.get("ENVIRONMENT") == "test", "Tests must run in test environment"

    logger.info("Test environment validation passed")


# Global variable to store the test user ID
_test_user_id = None


def get_test_user_id() -> str:
    """Override for get_current_user_id dependency in tests."""
    global _test_user_id
    if _test_user_id is None:
        raise RuntimeError("Test user not created yet")
    return _test_user_id


@pytest.fixture(scope="function")
def test_db():
    """Create a temporary database for testing."""
    # Create unique temporary database file in the current directory (project root)
    db_path = Path(f"test_{int(time.time() * 1000)}_{threading.get_ident()}_{uuid.uuid4().hex[:8]}.db")

    # Set environment variable for the test database
    original_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    # Clear the storage cache to ensure fresh instance with new database path
    get_storage.cache_clear()

    # Create database manager to initialize the database
    db_manager = DatabaseManager(db_path=str(db_path))

    yield str(db_path)

    # Cleanup - close all connections first
    try:
        if hasattr(db_manager, "engine") and db_manager.engine:
            db_manager.engine.dispose()
    except Exception as e:
        logger.debug(f"Failed to dispose database engine for {db_path}: {e}")

    # Remove test database file
    try:
        if db_path.exists():
            db_path.unlink()
    except Exception as e:
        logger.debug(f"Failed to delete test database file {db_path}: {e}")

    # Restore original environment variable
    if original_db_url is not None:
        os.environ["DATABASE_URL"] = original_db_url
    elif "DATABASE_URL" in os.environ:
        del os.environ["DATABASE_URL"]

    # Clear cache again to reset for next test
    get_storage.cache_clear()


@pytest.fixture(scope="function")
def client(test_db):
    """Create a test client with isolated database."""
    # Store original dependency overrides to restore later
    original_overrides = app.dependency_overrides.copy()

    # Override the authentication dependency for tests
    app.dependency_overrides[get_current_user_id] = get_test_user_id

    # Remove AuthenticationMiddleware from the app for testing
    # This allows tests to bypass JWT token validation while still testing business logic
    original_middleware = app.user_middleware.copy()
    # Filter out AuthenticationMiddleware

    app.user_middleware = [
        m for m in app.user_middleware if not isinstance(m.cls, type) or m.cls != AuthenticationMiddleware
    ]
    app.middleware_stack = None  # Force rebuild of middleware stack
    app.build_middleware_stack()

    # Create a test user in the database to satisfy foreign key constraints
    global _test_user_id
    db_manager = DatabaseManager(db_path=test_db)
    db_session = db_manager.SessionLocal()
    try:
        user_service = UserService(db_session)
        test_user = UserCreate(
            email="test@example.com", provider="google", provider_id="test-provider-id-123", name="Test User"
        )
        created_user = user_service.create_user(test_user)
        _test_user_id = created_user.id
        db_session.commit()
    finally:
        db_session.close()

    with TestClient(app) as test_client:
        yield test_client

    # Restore original middleware stack and dependency overrides
    app.user_middleware = original_middleware
    app.middleware_stack = None
    app.build_middleware_stack()
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original_overrides)
    _test_user_id = None


@pytest.fixture
def sample_session_data():
    """Sample session data for testing."""
    return {"project": "Test Project API"}


@pytest.fixture
def sample_answer_data():
    """Sample answer data for testing."""
    return {"answer_text": "This is a test answer for API testing"}


# ============================================================================
# Stripe Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_stripe_customer():
    """Create a mock Stripe customer object."""
    customer = Mock()
    customer.id = "cus_test123"
    customer.email = "test@example.com"
    customer.name = "Test User"
    customer.metadata = {"user_id": "test-user-id"}
    return customer


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


@pytest.fixture
def mock_stripe_checkout_session():
    """Create a mock Stripe checkout session object."""
    session = Mock()
    session.id = "cs_test123"
    session.url = "https://checkout.stripe.com/c/pay/cs_test123"
    session.customer = "cus_test123"
    session.subscription = "sub_test123"
    session.mode = "subscription"
    session.payment_status = "unpaid"
    return session


@pytest.fixture
def mock_stripe_portal_session():
    """Create a mock Stripe portal session object."""
    session = Mock()
    session.url = "https://billing.stripe.com/p/session_test123"
    return session


@pytest.fixture
def mock_stripe_event_checkout_completed():
    """Create a mock Stripe webhook event for checkout.session.completed."""
    event = Mock()
    event.id = "evt_test_checkout_123"
    event.type = "checkout.session.completed"
    event.data = Mock()
    event.data.object = Mock()
    event.data.object.id = "cs_test123"
    event.data.object.customer = "cus_test123"
    event.data.object.subscription = "sub_test123"
    event.data.object.mode = "subscription"
    return event


@pytest.fixture
def mock_stripe_event_subscription_created():
    """Create a mock Stripe webhook event for customer.subscription.created."""
    event = Mock()
    event.id = "evt_test_sub_created_123"
    event.type = "customer.subscription.created"
    event.data = Mock()
    event.data.object = Mock()
    event.data.object.id = "sub_test123"
    event.data.object.customer = "cus_test123"
    event.data.object.status = "active"
    event.data.object.current_period_start = 1704067200
    event.data.object.current_period_end = 1706745600
    event.data.object.cancel_at_period_end = False
    event.data.object.items = Mock()
    event.data.object.items.data = [Mock()]
    event.data.object.items.data[0].price = Mock()
    event.data.object.items.data[0].price.recurring = Mock()
    event.data.object.items.data[0].price.recurring.interval = "month"
    return event


@pytest.fixture
def mock_stripe_event_subscription_updated():
    """Create a mock Stripe webhook event for customer.subscription.updated."""
    event = Mock()
    event.id = "evt_test_sub_updated_123"
    event.type = "customer.subscription.updated"
    event.data = Mock()
    event.data.object = Mock()
    event.data.object.id = "sub_test123"
    event.data.object.customer = "cus_test123"
    event.data.object.status = "past_due"
    event.data.object.current_period_start = 1704067200
    event.data.object.current_period_end = 1706745600
    event.data.object.cancel_at_period_end = False
    event.data.object.items = Mock()
    event.data.object.items.data = [Mock()]
    event.data.object.items.data[0].price = Mock()
    event.data.object.items.data[0].price.recurring = Mock()
    event.data.object.items.data[0].price.recurring.interval = "month"
    return event


@pytest.fixture
def mock_stripe_event_subscription_deleted():
    """Create a mock Stripe webhook event for customer.subscription.deleted."""
    event = Mock()
    event.id = "evt_test_sub_deleted_123"
    event.type = "customer.subscription.deleted"
    event.data = Mock()
    event.data.object = Mock()
    event.data.object.id = "sub_test123"
    event.data.object.customer = "cus_test123"
    event.data.object.status = "canceled"
    event.data.object.current_period_start = 1704067200
    event.data.object.current_period_end = 1706745600
    event.data.object.cancel_at_period_end = False
    event.data.object.items = Mock()
    event.data.object.items.data = [Mock()]
    event.data.object.items.data[0].price = Mock()
    event.data.object.items.data[0].price.recurring = Mock()
    event.data.object.items.data[0].price.recurring.interval = "month"
    return event


@pytest.fixture
def stripe_test_env(monkeypatch):
    """Set up Stripe test environment variables."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake_key")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_fake_secret")
    monkeypatch.setenv("STRIPE_PRICE_ID_MONTHLY", "price_test_monthly")
    monkeypatch.setenv("STRIPE_PRICE_ID_ANNUAL", "price_test_annual")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
