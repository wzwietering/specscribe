"""Billing and subscription routes."""

import os
from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from specscribe.api.dependencies import get_current_user_id, get_database_manager
from specscribe.api.rate_limiting import (
    billing_checkout_rate_limiter,
    billing_portal_rate_limiter,
    check_billing_rate_limit,
)
from specscribe.core.services.stripe_service import StripeService
from specscribe.core.services.subscription_service import SubscriptionService
from specscribe.core.storage import DatabaseManager

router = APIRouter(prefix="/billing", tags=["billing"])


def get_stripe_service() -> StripeService:
    """Get Stripe service instance."""
    return StripeService()


def get_subscription_service() -> SubscriptionService:
    """Get subscription service instance."""
    db_manager = get_database_manager()
    stripe_service = get_stripe_service()
    return SubscriptionService(db_manager, stripe_service)


class CreateCheckoutSessionRequest(BaseModel):
    """Request to create checkout session."""

    plan_interval: str  # 'month' or 'year'


class CheckoutSessionResponse(BaseModel):
    """Response with checkout URL."""

    checkout_url: str


class PortalSessionResponse(BaseModel):
    """Response with portal URL."""

    portal_url: str


class SubscriptionResponse(BaseModel):
    """Subscription details response."""

    status: str
    plan_interval: str
    current_period_end: str
    cancel_at_period_end: bool


@router.post("/create-checkout-session", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    request_data: CreateCheckoutSessionRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    subscription_service: Annotated[SubscriptionService, Depends(get_subscription_service)],
) -> CheckoutSessionResponse:
    """Create Stripe Checkout session for subscription."""
    # Check rate limit
    check_billing_rate_limit(user_id, billing_checkout_rate_limiter, "checkout")

    # Validate plan interval
    if request_data.plan_interval not in ("month", "year"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="plan_interval must be 'month' or 'year'")

    # Get frontend URL for success/cancel redirects
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    success_url = f"{frontend_url}/billing?success=true"
    cancel_url = f"{frontend_url}/billing?canceled=true"

    try:
        _, checkout_url = subscription_service.initiate_checkout(
            user_id=user_id, plan_interval=request_data.plan_interval, success_url=success_url, cancel_url=cancel_url
        )
        return CheckoutSessionResponse(checkout_url=checkout_url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/create-portal-session", response_model=PortalSessionResponse)
async def create_portal_session(
    user_id: Annotated[str, Depends(get_current_user_id)],
    subscription_service: Annotated[SubscriptionService, Depends(get_subscription_service)],
) -> PortalSessionResponse:
    """Create Stripe Customer Portal session."""
    # Check rate limit
    check_billing_rate_limit(user_id, billing_portal_rate_limiter, "portal")

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    return_url = f"{frontend_url}/billing"

    try:
        portal_url = subscription_service.create_portal_session(user_id=user_id, return_url=return_url)
        return PortalSessionResponse(portal_url=portal_url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/subscription", response_model=SubscriptionResponse | None)
async def get_subscription(
    user_id: Annotated[str, Depends(get_current_user_id)],
    subscription_service: Annotated[SubscriptionService, Depends(get_subscription_service)],
) -> SubscriptionResponse | None:
    """Get user's current subscription."""
    subscription = subscription_service.get_user_subscription(user_id)
    if not subscription:
        return None

    return SubscriptionResponse(
        status=subscription.status,
        plan_interval=subscription.plan_interval,
        current_period_end=subscription.current_period_end.isoformat(),
        cancel_at_period_end=subscription.cancel_at_period_end,
    )


def _verify_webhook_signature(body: bytes, signature: str, stripe_service: StripeService) -> stripe.Event:
    """Verify webhook signature and return event."""
    try:
        return stripe_service.construct_webhook_event(body, signature)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload") from e
    except stripe.SignatureVerificationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid signature") from e


def _check_event_already_processed(db_session, subscription_service: SubscriptionService, event: stripe.Event) -> bool:
    """Check if event already processed via idempotency."""
    try:
        subscription_service.log_webhook_event(
            db_session=db_session, event_type=event.type, stripe_event_id=event.id, status="processing"
        )
        db_session.commit()
        return False
    except Exception:
        db_session.rollback()
        return True


def _process_webhook_event(db_session, subscription_service: SubscriptionService, event: stripe.Event) -> None:
    """Process webhook event based on type."""
    if event.type == "checkout.session.completed":
        session = stripe.checkout.Session.construct_from(event.data.object, stripe.api_key)
        subscription_service.handle_checkout_completed(db_session, session)

    elif event.type == "customer.subscription.created":
        subscription = stripe.Subscription.construct_from(event.data.object, stripe.api_key)
        subscription_service.handle_subscription_created(db_session, subscription)

    elif event.type == "customer.subscription.updated":
        subscription = stripe.Subscription.construct_from(event.data.object, stripe.api_key)
        subscription_service.handle_subscription_updated(db_session, subscription)

    elif event.type == "customer.subscription.deleted":
        subscription = stripe.Subscription.construct_from(event.data.object, stripe.api_key)
        subscription_service.handle_subscription_deleted(db_session, subscription)


def _log_webhook_success(db_session, subscription_service: SubscriptionService, event: stripe.Event) -> None:
    """Log successful webhook processing."""
    subscription_service.log_webhook_event(
        db_session=db_session, event_type=event.type, stripe_event_id=event.id, status="processed"
    )
    db_session.commit()


def _log_webhook_failure(
    db_manager: DatabaseManager, subscription_service: SubscriptionService, event: stripe.Event, error: Exception
) -> None:
    """Log failed webhook processing in separate transaction."""
    with db_manager.SessionLocal() as failure_session:
        subscription_service.log_webhook_event(
            db_session=failure_session,
            event_type=event.type,
            stripe_event_id=event.id,
            status=f"failed: {str(error)}",
        )
        failure_session.commit()


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    stripe_signature: Annotated[str, Header(alias="stripe-signature")],
    db_manager: Annotated[DatabaseManager, Depends(get_database_manager)],
) -> dict[str, str]:
    """Handle Stripe webhook events."""
    body = await request.body()
    stripe_service = get_stripe_service()
    event = _verify_webhook_signature(body, stripe_signature, stripe_service)
    subscription_service = SubscriptionService(db_manager, stripe_service)

    with db_manager.SessionLocal() as db_session:
        if _check_event_already_processed(db_session, subscription_service, event):
            return {"status": "success", "message": "Event already processed"}

        try:
            _process_webhook_event(db_session, subscription_service, event)
            _log_webhook_success(db_session, subscription_service, event)
        except Exception as e:
            db_session.rollback()
            _log_webhook_failure(db_manager, subscription_service, event, e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook processing failed"
            ) from e

    return {"status": "success"}
