"use client";

import { useState } from "react";
import { createCheckoutSession } from "@/lib/api/billing";

export function useCheckout() {
  const [checkoutLoading, setCheckoutLoading] = useState<"month" | "year" | null>(null);

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

  return { checkoutLoading, handleUpgrade };
}
