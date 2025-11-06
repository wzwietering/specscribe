/**
 * Billing API client for Stripe integration
 *
 * TODO: After running `npm run generate:types` in packages/shared-types,
 * replace these inline types with imports from "@specscribe/shared-types"
 */

import { apiClient } from "./apiClient";

export interface CheckoutSessionResponse {
  checkout_url: string;
}

export interface PortalSessionResponse {
  portal_url: string;
}

export interface Subscription {
  status: string;
  plan_interval: "month" | "year";
  current_period_end: string;
  cancel_at_period_end: boolean;
}

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
