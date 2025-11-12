"""Edge case and database constraint tests for billing system."""

import json
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
import stripe
from fastapi import status
from sqlalchemy.exc import IntegrityError

from specscribe.core.database_models import PaymentEventTable, SubscriptionTable, UserTable
from specscribe.core.storage import DatabaseManager


class TestDatabaseConstraints:
    """Test database constraints and data integrity."""

    def test_user_email_unique_constraint(self, test_db):
        """Test that duplicate user emails are prevented."""

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            # First user created successfully
            user1 = UserTable(
                id="user1",
                email="duplicate@example.com",
                provider="google",
                provider_id="provider1",
                name="User 1",
                tier="free",
            )
            session.add(user1)
            session.commit()

            # Second user with same email should fail
            user2 = UserTable(
                id="user2",
                email="duplicate@example.com",
                provider="google",
                provider_id="provider2",
                name="User 2",
                tier="free",
            )
            session.add(user2)
            with pytest.raises(IntegrityError):  # Should raise integrity error
                session.commit()

    def test_stripe_customer_id_allows_duplicates(self, test_db):
        """Test that stripe_customer_id is not unique (multiple users can share a customer in edge cases)."""

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user1 = UserTable(
                id="user1",
                email="user1@example.com",
                provider="google",
                provider_id="provider1",
                name="User 1",
                tier="free",
                stripe_customer_id="cus_shared",
            )
            session.add(user1)
            session.commit()

            user2 = UserTable(
                id="user2",
                email="user2@example.com",
                provider="google",
                provider_id="provider2",
                name="User 2",
                tier="free",
                stripe_customer_id="cus_shared",
            )
            session.add(user2)
            session.commit()  # Should succeed - no unique constraint on stripe_customer_id

            # Verify both users were created
            users = session.query(UserTable).filter(UserTable.stripe_customer_id == "cus_shared").all()
            assert len(users) == 2

    def test_stripe_subscription_id_unique_constraint(self, test_db):
        """Test that duplicate Stripe subscription IDs are prevented."""

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            # Create users
            user1 = UserTable(
                id="user1",
                email="user1@example.com",
                provider="google",
                provider_id="provider1",
                name="User 1",
                tier="free",
            )
            user2 = UserTable(
                id="user2",
                email="user2@example.com",
                provider="google",
                provider_id="provider2",
                name="User 2",
                tier="free",
            )
            session.add_all([user1, user2])
            session.commit()

            # First subscription
            sub1 = SubscriptionTable(
                user_id="user1",
                stripe_customer_id="cus_1",
                stripe_subscription_id="sub_duplicate",
                status="active",
                plan_interval="month",
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC),
            )
            session.add(sub1)
            session.commit()

            # Second subscription with same ID should fail
            sub2 = SubscriptionTable(
                user_id="user2",
                stripe_customer_id="cus_2",
                stripe_subscription_id="sub_duplicate",
                status="active",
                plan_interval="month",
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC),
            )
            session.add(sub2)
            with pytest.raises(IntegrityError):  # Should raise integrity error
                session.commit()

    def test_payment_event_stripe_event_id_unique_constraint(self, test_db):
        """Test that duplicate Stripe event IDs are prevented (idempotency)."""

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            event1 = PaymentEventTable(
                event_type="checkout.session.completed",
                stripe_event_id="evt_duplicate",
                status="processed",
            )
            session.add(event1)
            session.commit()

            event2 = PaymentEventTable(
                event_type="customer.subscription.created",
                stripe_event_id="evt_duplicate",
                status="processed",
            )
            session.add(event2)
            with pytest.raises(IntegrityError):  # Should raise integrity error
                session.commit()

    def test_subscription_foreign_key_constraint(self, test_db):
        """Test that subscription requires valid user_id."""

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            # Try to create subscription for non-existent user
            subscription = SubscriptionTable(
                user_id="nonexistent_user",
                stripe_customer_id="cus_test",
                stripe_subscription_id="sub_test",
                status="active",
                plan_interval="month",
            )
            session.add(subscription)
            with pytest.raises(IntegrityError):  # Should raise foreign key error
                session.commit()

    def test_user_deletion_cascades_to_subscriptions(self, test_db):
        """Test that deleting user cascades to subscriptions."""

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            # Create user and subscription
            user = UserTable(
                id="user_cascade",
                email="cascade@example.com",
                provider="google",
                provider_id="provider_cascade",
                name="Cascade User",
                tier="free",
            )
            session.add(user)
            session.commit()

            subscription = SubscriptionTable(
                user_id="user_cascade",
                stripe_customer_id="cus_cascade",
                stripe_subscription_id="sub_cascade",
                status="active",
                plan_interval="month",
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC),
            )
            session.add(subscription)
            session.commit()

            # Delete user
            session.delete(user)
            session.commit()

            # Check subscription is also deleted
            remaining_subs = session.query(SubscriptionTable).filter_by(user_id="user_cascade").all()
            assert len(remaining_subs) == 0


class TestTransactionRollbacks:
    """Test transaction rollback scenarios."""

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_checkout_completed_rollback_on_error(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_checkout_completed,
        mock_webhook_signature,
        mock_stripe_constructs,
    ):
        """Test that transaction rolls back if checkout processing fails."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        # Set up user

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        # Mock service to raise error during subscription retrieval
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_rollback_test"
        mock_event.type = "checkout.session.completed"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_checkout_completed["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        mock_session = Mock()
        mock_session.customer = "cus_test123"
        mock_session.subscription = "sub_test123"
        mock_construct_session.return_value = mock_session

        # Make get_subscription raise an error
        mock_service.get_subscription.side_effect = stripe.StripeError("Connection error")

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_checkout_completed),
            headers={"stripe-signature": mock_webhook_signature},
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        # Verify no subscription was created (rollback succeeded)
        with db_manager.SessionLocal() as session:
            subscription = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_test123").first()
            assert subscription is None

            # Verify event was logged as failed
            event = session.query(PaymentEventTable).filter_by(stripe_event_id="evt_rollback_test").first()
            assert event is not None
            assert "failed" in event.status

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_subscription_updated_rollback_on_error(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_subscription_updated,
        mock_webhook_signature,
        mock_stripe_constructs,
    ):
        """Test that transaction rolls back if subscription update fails."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        # Set up user and existing subscription

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
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC),
            )
            session.add(subscription)
            session.commit()

            original_status = subscription.status

        # Mock service
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_update_rollback"
        mock_event.type = "customer.subscription.updated"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_subscription_updated["data"]["object"]

        mock_service.construct_webhook_event.return_value = mock_event

        # Mock construct_from to raise an exception during processing
        mock_construct_subscription.side_effect = Exception("Database connection lost")

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(webhook_payload_subscription_updated),
            headers={"stripe-signature": mock_webhook_signature},
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        # Verify subscription status wasn't changed (rollback succeeded)
        with db_manager.SessionLocal() as session:
            subscription = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_test123").first()
            assert subscription.status == original_status


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_webhook_with_missing_customer_id(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_checkout_completed,
        mock_webhook_signature,
    ):
        """Test webhook processing when customer_id is missing."""
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        # Create event with missing customer_id
        payload = webhook_payload_checkout_completed.copy()
        payload["data"]["object"]["customer"] = None

        mock_event = Mock()
        mock_event.id = "evt_no_customer"
        mock_event.type = "checkout.session.completed"
        mock_event.data = Mock()
        mock_event.data.object = payload["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(payload),
            headers={"stripe-signature": mock_webhook_signature},
        )

        # Should succeed but do nothing
        assert response.status_code == status.HTTP_200_OK

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_webhook_with_missing_subscription_id(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_checkout_completed,
        mock_webhook_signature,
    ):
        """Test webhook processing when subscription_id is missing."""
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        # Create event with missing subscription_id
        payload = webhook_payload_checkout_completed.copy()
        payload["data"]["object"]["subscription"] = None

        mock_event = Mock()
        mock_event.id = "evt_no_subscription"
        mock_event.type = "checkout.session.completed"
        mock_event.data = Mock()
        mock_event.data.object = payload["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(payload),
            headers={"stripe-signature": mock_webhook_signature},
        )

        # Should succeed but do nothing
        assert response.status_code == status.HTTP_200_OK

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_webhook_for_unknown_customer(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_subscription_created,
        mock_webhook_signature,
        mock_stripe_constructs,
    ):
        """Test webhook processing for customer not in database."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_unknown_customer"
        mock_event.type = "customer.subscription.created"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_subscription_created["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        # Mock subscription for unknown customer
        mock_subscription = Mock()
        mock_subscription.id = "sub_unknown"
        mock_subscription.customer = "cus_unknown_12345"
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

        # Should succeed but do nothing (no user found)
        assert response.status_code == status.HTTP_200_OK

        # Verify no subscription was created

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            subscription = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_unknown").first()
            assert subscription is None

    @patch("specscribe.api.routes.billing.get_stripe_service")
    def test_webhook_with_invalid_timestamps(
        self,
        mock_get_service,
        client,
        test_db,
        webhook_payload_subscription_created,
        mock_webhook_signature,
        mock_stripe_constructs,
    ):
        """Test webhook processing with invalid timestamp values."""
        mock_construct_session, mock_construct_subscription = mock_stripe_constructs

        # Set up user

        db_manager = DatabaseManager(db_path=test_db)
        with db_manager.SessionLocal() as session:
            user = session.query(UserTable).filter_by(email="test@example.com").first()
            user.stripe_customer_id = "cus_test123"
            session.commit()

        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_event = Mock()
        mock_event.id = "evt_invalid_timestamps"
        mock_event.type = "customer.subscription.created"
        mock_event.data = Mock()
        mock_event.data.object = webhook_payload_subscription_created["data"]["object"]
        mock_service.construct_webhook_event.return_value = mock_event

        # Mock subscription with invalid timestamps (non-integers)
        mock_subscription = Mock()
        mock_subscription.id = "sub_invalid_time"
        mock_subscription.customer = "cus_test123"
        mock_subscription.status = "active"
        mock_subscription.current_period_start = "not_a_timestamp"
        mock_subscription.current_period_end = "also_not_a_timestamp"
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

        # Should succeed but not create subscription (invalid data)
        assert response.status_code == status.HTTP_200_OK

        # Verify no subscription was created
        with db_manager.SessionLocal() as session:
            subscription = session.query(SubscriptionTable).filter_by(stripe_subscription_id="sub_invalid_time").first()
            assert subscription is None

    def test_checkout_session_with_invalid_plan_interval(self, client, test_db):
        """Test that invalid plan interval is rejected."""
        response = client.post(
            "/api/v1/billing/create-checkout-session",
            json={"plan_interval": "invalid"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "plan_interval must be 'month' or 'year'" in response.json()["detail"]

    def test_create_portal_session_without_stripe_customer(self, client, test_db):
        """Test that portal creation fails for user without Stripe customer."""
        response = client.post(
            "/api/v1/billing/create-portal-session",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "has no Stripe customer" in response.json()["detail"]

    def test_get_subscription_returns_none_when_no_subscription(self, client, test_db):
        """Test that get subscription returns None when user has no subscription."""
        response = client.get(
            "/api/v1/billing/subscription",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() is None
