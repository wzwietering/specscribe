"use client";

import { FiCheck } from "react-icons/fi";

interface SubscriptionSuccessAlertProps {
  show: boolean;
}

export function SubscriptionSuccessAlert({ show }: SubscriptionSuccessAlertProps) {
  if (!show) return null;

  return (
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
  );
}
