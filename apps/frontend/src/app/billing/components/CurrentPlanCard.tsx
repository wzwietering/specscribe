"use client";

import { FiLoader, FiCreditCard, FiCalendar } from "react-icons/fi";
import type { Subscription } from "@/lib/api/billing";
import type { UsageStats } from "@/lib/api/usage";

interface CurrentPlanCardProps {
  isPro: boolean;
  subscription: Subscription | null;
  usage: UsageStats | null;
  portalLoading: boolean;
  onManageSubscription: () => void;
}

export function CurrentPlanCard({
  isPro,
  subscription,
  usage,
  portalLoading,
  onManageSubscription,
}: CurrentPlanCardProps) {
  return (
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
            onClick={onManageSubscription}
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
  );
}
