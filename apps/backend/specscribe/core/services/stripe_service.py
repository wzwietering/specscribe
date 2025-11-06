"""Stripe API service wrapper."""

import os
from typing import Any

import stripe


class StripeService:
    """Service for interacting with Stripe API."""

    def __init__(self) -> None:
        """Initialize Stripe with API key from environment."""
        api_key = os.getenv("STRIPE_SECRET_KEY")
        if not api_key:
            raise ValueError("STRIPE_SECRET_KEY environment variable is required")
        stripe.api_key = api_key

    def create_customer(self, email: str, name: str | None = None, metadata: dict[str, str] | None = None) -> str:
        """Create a Stripe customer and return customer ID."""
        customer_data: dict[str, Any] = {"email": email}
        if name:
            customer_data["name"] = name
        if metadata:
            customer_data["metadata"] = metadata

        customer = stripe.Customer.create(**customer_data)
        return customer.id

    def create_checkout_session(
        self, customer_id: str, price_id: str, success_url: str, cancel_url: str
    ) -> tuple[str, str]:
        """Create a Stripe Checkout session for subscription.

        Returns:
            Tuple of (session_id, checkout_url)
        """
        session = stripe.checkout.Session.create(
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
        )
        # Both id and url are always present for checkout sessions
        assert session.id is not None
        assert session.url is not None
        return session.id, session.url

    def create_portal_session(self, customer_id: str, return_url: str) -> str:
        """Create a Stripe Customer Portal session.

        Returns:
            Portal URL for customer to manage subscription
        """
        session = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
        return session.url

    def get_subscription(self, subscription_id: str) -> stripe.Subscription:
        """Retrieve a subscription by ID."""
        return stripe.Subscription.retrieve(subscription_id)

    def cancel_subscription(self, subscription_id: str, at_period_end: bool = True) -> stripe.Subscription:
        """Cancel a subscription.

        Args:
            subscription_id: Stripe subscription ID
            at_period_end: If True, cancel at end of billing period (default)
        """
        if at_period_end:
            return stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
        return stripe.Subscription.cancel(subscription_id)

    def construct_webhook_event(self, payload: bytes, signature: str) -> stripe.Event:
        """Construct and verify a webhook event from Stripe.

        Args:
            payload: Raw request body bytes
            signature: Stripe-Signature header value

        Raises:
            stripe.error.SignatureVerificationError: If signature is invalid
            ValueError: If webhook secret is not configured
        """
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        if not webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET environment variable is required")

        return stripe.Webhook.construct_event(payload, signature, webhook_secret)

    def get_price_id(self, plan_interval: str) -> str:
        """Get Stripe Price ID for plan interval.

        Args:
            plan_interval: 'month' or 'year'

        Returns:
            Stripe Price ID

        Raises:
            ValueError: If plan_interval is invalid or price ID not configured
        """
        if plan_interval == "month":
            price_id = os.getenv("STRIPE_PRICE_ID_MONTHLY")
            if not price_id:
                raise ValueError("STRIPE_PRICE_ID_MONTHLY environment variable is required")
            return price_id
        if plan_interval == "year":
            price_id = os.getenv("STRIPE_PRICE_ID_ANNUAL")
            if not price_id:
                raise ValueError("STRIPE_PRICE_ID_ANNUAL environment variable is required")
            return price_id
        raise ValueError(f"Invalid plan_interval: {plan_interval}. Must be 'month' or 'year'")
