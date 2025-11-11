"use client";

import { useState, useEffect } from "react";
import { getSubscription, type Subscription } from "@/lib/api/billing";

export function useSubscription() {
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [loading, setLoading] = useState(true);

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

  useEffect(() => {
    loadSubscription();
  }, []);

  return { subscription, loading, refetch: loadSubscription };
}
