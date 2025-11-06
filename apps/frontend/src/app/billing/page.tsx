import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { BillingPageClient } from "./BillingPageClient";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Billing | SpecScribe",
  description: "Manage your subscription and billing settings",
};

export default function BillingPage() {
  return (
    <ProtectedRoute redirectTo="/login">
      <BillingPageClient />
    </ProtectedRoute>
  );
}
