"use client";

/**
 * Billing page for subscription management
 * Allows users to upgrade to Pro, manage subscription via Stripe portal
 */

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FiLoader } from "react-icons/fi";
import { useAuth } from "@/components/auth/AuthProvider";
import { useQuota } from "@/contexts/QuotaContext";
import { useSubscription } from "./hooks/useSubscription";
import { useCheckout } from "./hooks/useCheckout";
import { usePortal } from "./hooks/usePortal";
import { SubscriptionSuccessAlert } from "./components/SubscriptionSuccessAlert";
import { CurrentPlanCard } from "./components/CurrentPlanCard";
import { UpgradeOptionsCard } from "./components/UpgradeOptionsCard";

export function BillingPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuth();
  const { usage, refetch: refetchUsage } = useQuota();

  const { subscription, loading, refetch: refetchSubscription } = useSubscription();
  const { checkoutLoading, handleUpgrade } = useCheckout();
  const { portalLoading, handleManageSubscription } = usePortal();
  const [showSuccess, setShowSuccess] = useState(false);

  // Check for success/canceled query params
  useEffect(() => {
    const success = searchParams?.get("success");
    const canceled = searchParams?.get("canceled");

    if (success === "true") {
      setShowSuccess(true);
      refetchSubscription();
      refetchUsage();
      router.replace("/billing");
    } else if (canceled === "true") {
      router.replace("/billing");
    }
  }, [searchParams, router, refetchUsage, refetchSubscription]);

  const tier = user?.tier || "free";
  const isPro = tier === "pro";

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <SubscriptionSuccessAlert show={showSuccess} />

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
            <CurrentPlanCard
              isPro={isPro}
              subscription={subscription}
              usage={usage}
              portalLoading={portalLoading}
              onManageSubscription={handleManageSubscription}
            />

            {!isPro && (
              <UpgradeOptionsCard
                checkoutLoading={checkoutLoading}
                onUpgrade={handleUpgrade}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
