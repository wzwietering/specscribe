"""Subscription business logic service."""

import logging
from datetime import UTC, datetime

import stripe
from sqlalchemy.orm import Session

from specscribe.core.database_models import PaymentEventTable, SubscriptionTable, UserTable
from specscribe.core.services.stripe_service import StripeService
from specscribe.core.storage import DatabaseManager

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Service for managing subscription business logic."""

    def __init__(self, storage: DatabaseManager, stripe_service: StripeService):
        self.storage = storage
        self.stripe_service = stripe_service

    def initiate_checkout(self, user_id: str, plan_interval: str, success_url: str, cancel_url: str) -> tuple[str, str]:
        """Initiate checkout session for user subscription.

        Creates Stripe customer if needed, then creates checkout session.

        Args:
            user_id: User ID
            plan_interval: 'month' or 'year'
            success_url: URL to redirect after successful checkout
            cancel_url: URL to redirect if checkout cancelled

        Returns:
            Tuple of (session_id, checkout_url)
        """
        with self.storage.SessionLocal() as db_session:
            user = db_session.get(UserTable, user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")

            # Create Stripe customer if doesn't exist
            if not user.stripe_customer_id:
                customer_id = self.stripe_service.create_customer(
                    email=user.email, name=user.name, metadata={"user_id": user_id}
                )
                user.stripe_customer_id = customer_id
                db_session.commit()
            else:
                customer_id = user.stripe_customer_id

            # Get price ID for interval
            price_id = self.stripe_service.get_price_id(plan_interval)

            # Create checkout session
            session_id, checkout_url = self.stripe_service.create_checkout_session(
                customer_id=customer_id, price_id=price_id, success_url=success_url, cancel_url=cancel_url
            )

            return session_id, checkout_url

    def create_portal_session(self, user_id: str, return_url: str) -> str:
        """Create customer portal session for user.

        Args:
            user_id: User ID
            return_url: URL to return to from portal

        Returns:
            Portal URL
        """
        with self.storage.SessionLocal() as db_session:
            user = db_session.get(UserTable, user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")

            if not user.stripe_customer_id:
                raise ValueError(f"User {user_id} has no Stripe customer")

            return self.stripe_service.create_portal_session(user.stripe_customer_id, return_url)

    def get_user_subscription(self, user_id: str) -> SubscriptionTable | None:
        """Get user's active subscription."""
        with self.storage.SessionLocal() as db_session:
            return db_session.query(SubscriptionTable).filter(SubscriptionTable.user_id == user_id).first()

    def handle_checkout_completed(self, db_session: Session, session: stripe.checkout.Session) -> None:
        """Handle checkout.session.completed webhook event."""
        customer_id = session.customer
        subscription_id = session.subscription

        if not customer_id or not subscription_id:
            return

        # Get subscription details - subscription_id could be a Subscription object or str
        if isinstance(subscription_id, str):
            subscription = self.stripe_service.get_subscription(subscription_id)
        else:
            subscription = subscription_id
        self._upsert_subscription(db_session, subscription)

    def handle_subscription_created(self, db_session: Session, subscription: stripe.Subscription) -> None:
        """Handle customer.subscription.created webhook event."""
        self._upsert_subscription(db_session, subscription)

    def handle_subscription_updated(self, db_session: Session, subscription: stripe.Subscription) -> None:
        """Handle customer.subscription.updated webhook event."""
        self._upsert_subscription(db_session, subscription)

    def handle_subscription_deleted(self, db_session: Session, subscription: stripe.Subscription) -> None:
        """Handle customer.subscription.deleted webhook event."""
        # Find user by customer ID
        user = db_session.query(UserTable).filter(UserTable.stripe_customer_id == subscription.customer).first()
        if not user:
            return

        # Downgrade user tier
        old_tier = user.tier
        user.tier = "free"

        logger.info(
            "User tier downgraded",
            extra={
                "user_id": user.id,
                "old_tier": old_tier,
                "new_tier": "free",
                "subscription_id": subscription.id,
                "reason": "subscription_deleted",
            },
        )

        # Update or delete subscription record
        sub_record = (
            db_session.query(SubscriptionTable)
            .filter(SubscriptionTable.stripe_subscription_id == subscription.id)
            .first()
        )
        if sub_record:
            sub_record.status = "canceled"
            sub_record.updated_at = datetime.now(UTC)
            logger.info(
                "Subscription record updated to canceled",
                extra={"user_id": user.id, "subscription_id": subscription.id},
            )

    def _determine_plan_interval(self, subscription: stripe.Subscription) -> str:
        """Extract plan interval from subscription."""
        if subscription.items and subscription.items.data:
            price = subscription.items.data[0].price
            if price.recurring and price.recurring.interval == "year":
                return "year"
        return "month"

    def _extract_subscription_timestamps(self, subscription: stripe.Subscription) -> tuple[int, int] | None:
        """Extract and validate timestamps from subscription."""
        period_start = getattr(subscription, "current_period_start", None)
        period_end = getattr(subscription, "current_period_end", None)

        if not isinstance(period_start, int) or not isinstance(period_end, int):
            return None

        return period_start, period_end

    def _update_subscription_record(
        self,
        sub_record: SubscriptionTable,
        subscription: stripe.Subscription,
        plan_interval: str,
        timestamps: tuple[int, int],
    ) -> None:
        """Update existing subscription record."""
        period_start, period_end = timestamps
        sub_record.status = subscription.status
        sub_record.plan_interval = plan_interval
        sub_record.current_period_start = datetime.fromtimestamp(period_start, UTC)
        sub_record.current_period_end = datetime.fromtimestamp(period_end, UTC)
        sub_record.cancel_at_period_end = subscription.cancel_at_period_end or False
        sub_record.updated_at = datetime.now(UTC)

    def _create_subscription_record(
        self, user: UserTable, subscription: stripe.Subscription, plan_interval: str, timestamps: tuple[int, int]
    ) -> SubscriptionTable:
        """Create new subscription record."""
        period_start, period_end = timestamps
        return SubscriptionTable(
            user_id=user.id,
            stripe_customer_id=subscription.customer,
            stripe_subscription_id=subscription.id,
            status=subscription.status,
            plan_interval=plan_interval,
            current_period_start=datetime.fromtimestamp(period_start, UTC),
            current_period_end=datetime.fromtimestamp(period_end, UTC),
            cancel_at_period_end=subscription.cancel_at_period_end or False,
        )

    def _update_user_tier(self, user: UserTable, subscription: stripe.Subscription) -> None:
        """Update user tier based on subscription status."""
        old_tier = user.tier
        new_tier = "pro" if subscription.status in ("active", "trialing") else old_tier

        if old_tier != new_tier:
            user.tier = new_tier
            logger.info(
                "User tier changed",
                extra={
                    "user_id": user.id,
                    "old_tier": old_tier,
                    "new_tier": new_tier,
                    "subscription_id": subscription.id,
                    "subscription_status": subscription.status,
                    "reason": "subscription_update",
                },
            )

    def _upsert_subscription(self, db_session: Session, subscription: stripe.Subscription) -> None:
        """Create or update subscription record and upgrade user tier."""
        user = db_session.query(UserTable).filter(UserTable.stripe_customer_id == subscription.customer).first()
        if not user:
            return

        plan_interval = self._determine_plan_interval(subscription)
        timestamps = self._extract_subscription_timestamps(subscription)
        if not timestamps:
            return

        sub_record = (
            db_session.query(SubscriptionTable)
            .filter(SubscriptionTable.stripe_subscription_id == subscription.id)
            .first()
        )

        if sub_record:
            logger.info(
                "Updating subscription",
                extra={
                    "user_id": user.id,
                    "subscription_id": subscription.id,
                    "status": subscription.status,
                    "plan_interval": plan_interval,
                },
            )
            self._update_subscription_record(sub_record, subscription, plan_interval, timestamps)
        else:
            logger.info(
                "Creating new subscription",
                extra={
                    "user_id": user.id,
                    "subscription_id": subscription.id,
                    "status": subscription.status,
                    "plan_interval": plan_interval,
                },
            )
            new_record = self._create_subscription_record(user, subscription, plan_interval, timestamps)
            db_session.add(new_record)

        self._update_user_tier(user, subscription)

    def log_webhook_event(
        self, db_session: Session, event_type: str, stripe_event_id: str, status: str, user_id: str | None = None
    ) -> None:
        """Log webhook event for audit trail.

        Args:
            db_session: Database session
            event_type: Stripe event type
            stripe_event_id: Stripe event ID (for idempotency)
            status: Event processing status
            user_id: Optional user ID
        """
        event = PaymentEventTable(
            user_id=user_id, event_type=event_type, stripe_event_id=stripe_event_id, status=status
        )
        db_session.add(event)
