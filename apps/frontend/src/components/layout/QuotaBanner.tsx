"use client";

/**
 * Quota banner component for prominent usage warnings
 * Shows dismissible alerts when approaching or exceeding quota limits
 */

import { useState, useEffect } from "react";
import { FiAlertTriangle, FiX } from "react-icons/fi";
import { useQuota } from "@/contexts/QuotaContext";
import { formatResetDate, getUpgradeMessage, calculatePercentUsed, MS_PER_DAY } from "@/lib/utils/quota";
import { useAuth } from "@/components/auth/AuthProvider";

interface BannerDismissal {
  dismissedAt: string;
  quotaState: "urgent" | "critical";
  suppressUntil: string;
}

const DISMISSAL_KEY = "quota-banner-dismissal";
const DISMISSAL_DURATION_MS = MS_PER_DAY;

function getBannerDismissal(): BannerDismissal | null {
  if (typeof window === "undefined") return null;

  try {
    const stored = localStorage.getItem(DISMISSAL_KEY);
    if (!stored) return null;
    return JSON.parse(stored);
  } catch {
    return null;
  }
}

function setBannerDismissal(state: "urgent" | "critical") {
  if (typeof window === "undefined") return;

  try {
    const dismissal: BannerDismissal = {
      dismissedAt: new Date().toISOString(),
      quotaState: state,
      suppressUntil: new Date(Date.now() + DISMISSAL_DURATION_MS).toISOString(),
    };

    localStorage.setItem(DISMISSAL_KEY, JSON.stringify(dismissal));
  } catch (error) {
    console.error("Failed to save banner dismissal:", error);
  }
}

function clearBannerDismissal() {
  if (typeof window === "undefined") return;

  try {
    localStorage.removeItem(DISMISSAL_KEY);
  } catch (error) {
    console.error("Failed to clear banner dismissal:", error);
  }
}

/**
 * Determine if banner should be shown based on dismissal state
 */
function shouldShowBanner(
  shouldShow: boolean,
  currentState: "urgent" | "critical",
  dismissal: BannerDismissal | null
): boolean {
  if (!shouldShow) return false;
  if (!dismissal) return true;

  const now = new Date();
  const suppressUntil = new Date(dismissal.suppressUntil);

  // Show if state worsened (urgent → critical)
  if (dismissal.quotaState === "urgent" && currentState === "critical") {
    return true;
  }

  // Show if suppression period elapsed
  return now >= suppressUntil;
}

export function QuotaBanner() {
  const { isUrgent, isCritical, resetDate, usage } = useQuota();
  const { user } = useAuth();
  const [isVisible, setIsVisible] = useState(false);

  const shouldShow = isUrgent || isCritical;
  const currentState = isCritical ? "critical" : "urgent";

  useEffect(() => {
    if (!shouldShow) {
      setIsVisible(false);
      clearBannerDismissal();
      return;
    }

    const dismissal = getBannerDismissal();
    const visible = shouldShowBanner(shouldShow, currentState, dismissal);

    setIsVisible(visible);

    // Clear dismissal if showing again (state worsened or time elapsed)
    if (visible && dismissal) {
      clearBannerDismissal();
    }
  }, [shouldShow, currentState]);

  const handleDismiss = () => {
    setIsVisible(false);
    setBannerDismissal(currentState);
  };

  const handleUpgrade = () => {
    window.location.href = "/billing";
  };

  if (!isVisible || !resetDate || !usage) {
    return null;
  }

  const tier = user?.tier || "free";
  // Calculate days into window (for rolling window, approximate from reset date)
  const daysIntoWindow = Math.max(0, Math.floor((Date.now() - (resetDate.getTime() - usage.windowDays * MS_PER_DAY)) / MS_PER_DAY));
  const percentUsed = calculatePercentUsed(usage.quotaLimit - usage.quotaRemaining, usage.quotaLimit);
  const upgradeMessage = getUpgradeMessage(percentUsed, daysIntoWindow, tier);

  const bgColor = isCritical ? "bg-jasper-red-50" : "bg-amber-50";
  const borderColor = isCritical ? "border-jasper-red-200" : "border-amber-200";
  const iconColor = isCritical ? "text-jasper-red-600" : "text-amber-600";
  const textColor = isCritical ? "text-jasper-red-900" : "text-amber-900";

  return (
    <section
      role="alert"
      aria-live="assertive"
      aria-labelledby="quota-banner-title"
      className={`w-full border-b ${bgColor} ${borderColor}`}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3">
        <div className="flex items-start gap-4">
          {/* Icon */}
          <FiAlertTriangle
            className={`w-5 h-5 mt-0.5 flex-shrink-0 ${iconColor}`}
            aria-hidden="true"
          />

          {/* Content */}
          <div className="flex-1 min-w-0">
            <h2 id="quota-banner-title" className={`text-sm font-semibold ${textColor}`}>
              {isCritical ? "Quota Exceeded" : "Approaching Quota Limit"}
            </h2>
            <p className={`text-sm ${textColor} mt-1`}>
              {isCritical
                ? `You've used all ${usage.quotaLimit} sessions this month.`
                : `Only ${usage.quotaRemaining} session${usage.quotaRemaining === 1 ? "" : "s"} remaining this month.`}
              {" "}
              <span className="font-medium">
                Resets {formatResetDate(resetDate)}
              </span>
            </p>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 flex-shrink-0">
            {tier === "free" && upgradeMessage && (
              <button
                onClick={handleUpgrade}
                className="btn-base btn-md bg-deep-indigo-400 text-white hover:bg-deep-indigo-500"
              >
                Upgrade to Pro
              </button>
            )}

            <button
              onClick={handleDismiss}
              aria-label="Dismiss notification"
              className={`p-2 rounded-md hover:bg-black/5 focus:outline-2 focus:outline-offset-2 focus:outline-current transition-colors ${textColor}`}
            >
              <FiX className="w-5 h-5" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
