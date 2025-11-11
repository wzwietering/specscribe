"use client";

import { PlanOption } from "./PlanOption";

interface UpgradeOptionsCardProps {
  checkoutLoading: "month" | "year" | null;
  onUpgrade: (planInterval: "month" | "year") => void;
}

export function UpgradeOptionsCard({
  checkoutLoading,
  onUpgrade,
}: UpgradeOptionsCardProps) {
  const monthlyFeatures = [
    "10,000 sessions per month",
    "Priority support",
    "Advanced export options",
  ];

  const annualFeatures = [
    "10,000 sessions per month",
    "Priority support",
    "Advanced export options",
    "2 months free",
  ];

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">
        Upgrade to Pro
      </h2>
      <p className="text-gray-600 mb-6">
        Unlock unlimited sessions and advanced features
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <PlanOption
          name="Monthly"
          price="€9.99"
          period="month"
          features={monthlyFeatures}
          onSubscribe={() => onUpgrade("month")}
          isLoading={checkoutLoading === "month"}
          disabled={checkoutLoading !== null}
        />

        <PlanOption
          name="Annual"
          price="€99"
          period="year"
          pricePerMonth="€8.25/month"
          features={annualFeatures}
          onSubscribe={() => onUpgrade("year")}
          isLoading={checkoutLoading === "year"}
          disabled={checkoutLoading !== null}
          featured
          featuredLabel="Save 17%"
        />
      </div>

      <p className="text-xs text-gray-500 mt-6 text-center">
        All plans are secured by Stripe. Cancel anytime.
      </p>
    </div>
  );
}
