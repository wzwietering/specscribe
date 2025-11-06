"use client";

/**
 * Billing page for subscription management
 * Allows users to upgrade to Pro, manage subscription via Stripe portal
 */

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FiCheck, FiLoader, FiCreditCard, FiCalendar } from "react-icons/fi";
import { useAuth } from "@/components/auth/AuthProvider";
import { useQuota } from "@/contexts/QuotaContext";
import {
  createCheckoutSession,
  createPortalSession,
  getSubscription,
  type Subscription,
} from "@/lib/api/billing";

export function BillingPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuth();
  const { usage, refetch: refetchUsage } = useQuota();

  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [loading, setLoading] = useState(true);
  const [checkoutLoading, setCheckoutLoading] = useState<"month" | "year" | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);

  // Check for success/canceled query params
  useEffect(() => {
    const success = searchParams?.get("success");
    const canceled = searchParams?.get("canceled");

    if (success === "true") {
      setShowSuccess(true);
      // Refetch subscription and usage data
      loadSubscription();
      refetchUsage();
      // Clear query params
      router.replace("/billing");
    } else if (canceled === "true") {
      // Clear query params
      router.replace("/billing");
    }
  }, [searchParams, router, refetchUsage]);

  // Load subscription on mount
  useEffect(() => {
    loadSubscription();
  }, []);

  async function loadSubscription() {
    try {
      const sub = await getSubscription();
      setSubscription(sub);
    } catch (error) {
      console.error("Failed to load subscription:", error);
    } finally {
      setLoading(false);
    }
  }

  async function handleUpgrade(planInterval: "month" | "year") {
    setCheckoutLoading(planInterval);
    try {
      const { checkout_url } = await createCheckoutSession(planInterval);
      window.location.href = checkout_url;
    } catch (error) {
      console.error("Failed to create checkout session:", error);
      alert("Failed to start checkout. Please try again.");
      setCheckoutLoading(null);
    }
  }

  async function handleManageSubscription() {
    setPortalLoading(true);
    try {
      const { portal_url } = await createPortalSession();
      window.location.href = portal_url;
    } catch (error) {
      console.error("Failed to create portal session:", error);
      alert("Failed to open billing portal. Please try again.");
      setPortalLoading(false);
    }
  }

  const tier = user?.tier || "free";
  const isPro = tier === "pro";

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {/* Success Message */}
        {showSuccess && (
          <div className="mb-8 bg-green-50 border border-green-200 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <FiCheck className="w-5 h-5 text-green-600 flex-shrink-0" />
              <div>
                <h3 className="text-sm font-semibold text-green-900">
                  Subscription activated!
                </h3>
                <p className="text-sm text-green-700 mt-1">
                  Welcome to SpecScribe Pro. Your quota has been updated.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Page Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Billing & Subscription</h1>
          <p className="text-gray-600 mt-2">
            Manage your subscription and view billing details
          </p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <FiLoader className="w-8 h-8 animate-spin text-deep-indigo-400" />
          </div>
        ) : (
          <>
            {/* Current Plan */}
            <div className="bg-white rounded-lg border border-gray-200 p-6 mb-8">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Current Plan</h2>

              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-3">
                    <span className="text-2xl font-bold text-gray-900">
                      {isPro ? "Pro" : "Free"}
                    </span>
                    {isPro && subscription && (
                      <span className="px-2.5 py-0.5 bg-deep-indigo-100 text-deep-indigo-700 text-sm font-medium rounded-full">
                        {subscription.plan_interval === "month" ? "Monthly" : "Annual"}
                      </span>
                    )}
                  </div>

                  {usage && (
                    <p className="text-gray-600 mt-2">
                      {usage.quotaRemaining} of {usage.quotaLimit} sessions remaining
                    </p>
                  )}

                  {isPro && subscription && (
                    <div className="mt-4 space-y-2 text-sm text-gray-600">
                      <div className="flex items-center gap-2">
                        <FiCalendar className="w-4 h-4" />
                        <span>
                          Renews on{" "}
                          {new Date(subscription.current_period_end).toLocaleDateString()}
                        </span>
                      </div>
                      {subscription.cancel_at_period_end && (
                        <p className="text-amber-600 font-medium">
                          Cancels at end of billing period
                        </p>
                      )}
                    </div>
                  )}
                </div>

                {isPro && (
                  <button
                    onClick={handleManageSubscription}
                    disabled={portalLoading}
                    className="btn-base btn-md bg-gray-100 text-gray-700 hover:bg-gray-200 flex items-center gap-2"
                  >
                    {portalLoading ? (
                      <FiLoader className="w-4 h-4 animate-spin" />
                    ) : (
                      <FiCreditCard className="w-4 h-4" />
                    )}
                    Manage Subscription
                  </button>
                )}
              </div>
            </div>

            {/* Upgrade Options */}
            {!isPro && (
              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">
                  Upgrade to Pro
                </h2>
                <p className="text-gray-600 mb-6">
                  Unlock unlimited sessions and advanced features
                </p>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Monthly Plan */}
                  <div className="border border-gray-200 rounded-lg p-6 hover:border-deep-indigo-400 transition-colors">
                    <div className="mb-4">
                      <h3 className="text-lg font-semibold text-gray-900">Monthly</h3>
                      <div className="flex items-baseline mt-2">
                        <span className="text-3xl font-bold text-gray-900">€9.99</span>
                        <span className="text-gray-600 ml-2">/month</span>
                      </div>
                    </div>

                    <ul className="space-y-3 mb-6">
                      <li className="flex items-start gap-2">
                        <FiCheck className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                        <span className="text-sm text-gray-600">
                          10,000 sessions per month
                        </span>
                      </li>
                      <li className="flex items-start gap-2">
                        <FiCheck className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                        <span className="text-sm text-gray-600">Priority support</span>
                      </li>
                      <li className="flex items-start gap-2">
                        <FiCheck className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                        <span className="text-sm text-gray-600">
                          Advanced export options
                        </span>
                      </li>
                    </ul>

                    <button
                      onClick={() => handleUpgrade("month")}
                      disabled={checkoutLoading !== null}
                      className="btn-base btn-md w-full bg-deep-indigo-400 text-white hover:bg-deep-indigo-500 disabled:opacity-50"
                    >
                      {checkoutLoading === "month" ? (
                        <FiLoader className="w-5 h-5 animate-spin mx-auto" />
                      ) : (
                        "Subscribe Monthly"
                      )}
                    </button>
                  </div>

                  {/* Annual Plan */}
                  <div className="border-2 border-deep-indigo-400 rounded-lg p-6 relative">
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                      <span className="bg-deep-indigo-400 text-white px-3 py-1 rounded-full text-xs font-semibold">
                        Save 17%
                      </span>
                    </div>

                    <div className="mb-4">
                      <h3 className="text-lg font-semibold text-gray-900">Annual</h3>
                      <div className="flex items-baseline mt-2">
                        <span className="text-3xl font-bold text-gray-900">€99</span>
                        <span className="text-gray-600 ml-2">/year</span>
                      </div>
                      <p className="text-sm text-gray-500 mt-1">€8.25/month</p>
                    </div>

                    <ul className="space-y-3 mb-6">
                      <li className="flex items-start gap-2">
                        <FiCheck className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                        <span className="text-sm text-gray-600">
                          10,000 sessions per month
                        </span>
                      </li>
                      <li className="flex items-start gap-2">
                        <FiCheck className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                        <span className="text-sm text-gray-600">Priority support</span>
                      </li>
                      <li className="flex items-start gap-2">
                        <FiCheck className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                        <span className="text-sm text-gray-600">
                          Advanced export options
                        </span>
                      </li>
                      <li className="flex items-start gap-2">
                        <FiCheck className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                        <span className="text-sm text-gray-600 font-medium">
                          2 months free
                        </span>
                      </li>
                    </ul>

                    <button
                      onClick={() => handleUpgrade("year")}
                      disabled={checkoutLoading !== null}
                      className="btn-base btn-md w-full bg-deep-indigo-400 text-white hover:bg-deep-indigo-500 disabled:opacity-50"
                    >
                      {checkoutLoading === "year" ? (
                        <FiLoader className="w-5 h-5 animate-spin mx-auto" />
                      ) : (
                        "Subscribe Annually"
                      )}
                    </button>
                  </div>
                </div>

                <p className="text-xs text-gray-500 mt-6 text-center">
                  All plans are secured by Stripe. Cancel anytime.
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
