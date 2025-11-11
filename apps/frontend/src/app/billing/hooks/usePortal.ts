"use client";

import { useState } from "react";
import { createPortalSession } from "@/lib/api/billing";

export function usePortal() {
  const [portalLoading, setPortalLoading] = useState(false);

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

  return { portalLoading, handleManageSubscription };
}
