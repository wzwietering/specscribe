/**
 * Billing API client for Stripe integration
 */

import { apiClient } from "./apiClient";
import type { components } from "@specscribe/shared-types";

export type CheckoutSessionResponse = components["schemas"]["CheckoutSessionResponse"];
export type PortalSessionResponse = components["schemas"]["PortalSessionResponse"];
export type Subscription = components["schemas"]["SubscriptionResponse"];

/**
 * Create a Stripe Checkout session for subscription
 */
export async function createCheckoutSession(
  planInterval: "month" | "year"
): Promise<CheckoutSessionResponse> {
  return apiClient.post<CheckoutSessionResponse>(
    "/api/v1/billing/create-checkout-session",
    { plan_interval: planInterval }
  );
}

/**
 * Create a Stripe Customer Portal session
 */
export async function createPortalSession(): Promise<PortalSessionResponse> {
  return apiClient.post<PortalSessionResponse>(
    "/api/v1/billing/create-portal-session"
  );
}

/**
 * Get user's current subscription
 */
export async function getSubscription(): Promise<Subscription | null> {
  return apiClient.get<Subscription | null>("/api/v1/billing/subscription");
}
