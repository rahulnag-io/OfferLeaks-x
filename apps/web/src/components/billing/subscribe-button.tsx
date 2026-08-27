"use client";

import Script from "next/script";
import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * Handles both directions of the M6 billing loop from a single button:
 * - Not subscribed to this plan: POSTs `{ plan_key }` to the BFF, then
 *   opens Razorpay Checkout.js with the returned subscription ID and key.
 *   This component never collects or sees card details itself (§0.11).
 * - Currently on this plan: POSTs to the cancel endpoint, then reloads
 *   so the plan/usage indicator reflects the new
 *   `cancel_at_period_end` state.
 *
 * A plain `<button>`-driven client component, not a form -- matches
 * `AnalysisHistoryItem`'s re-check button pattern (fetch + local loading/
 * error state) rather than introducing a new interaction pattern.
 */
declare global {
  interface Window {
    Razorpay?: new (options: {
      key: string;
      subscription_id: string;
      name?: string;
      handler?: () => void;
      modal?: {
        ondismiss?: () => void;
      };
    }) => {
      open: () => void;
    };
  }
}

export function SubscribeButton({
  planKey,
  isCurrentPlan,
  isFreePlan,
}: {
  planKey: string;
  isCurrentPlan: boolean;
  isFreePlan: boolean;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubscribe() {
    setError(null);
    setLoading(true);
    try {
      const response = await fetch("/api/billing/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_key: planKey }),
      });
      const body = (await response.json().catch(() => null)) as
        | {
          checkout_url?: string | null;
          razorpay_subscription_id?: string | null;
          razorpay_key_id?: string;
          detail?: string;
        }
        | null;

      if (!response.ok) {
        setError(body?.detail ?? "Something went wrong starting checkout. Please try again.");
        setLoading(false);
        return;
      }
      if (!window.Razorpay) {
        setError("Payment checkout is still loading. Please try again.");
        setLoading(false);
        return;
      }

      if (!body?.razorpay_subscription_id || !body.razorpay_key_id) {
        setError("Checkout couldn't be started. Please try again.");
        setLoading(false);
        return;
      }

      const checkout = new window.Razorpay({
        key: body.razorpay_key_id,
        subscription_id: body.razorpay_subscription_id,
        name: "OfferLeaks",
        handler: () => {
          // The `subscription.activated` webhook is the source of truth
          // for granting Pro entitlements/credits. This only reflects the
          // state once the webhook has landed.
          window.location.href = "/dashboard/plans";
        },
        modal: {
          ondismiss: () => setLoading(false),
        },
      });
      checkout.open();
    } catch {
      setError("Couldn't reach the server. Please check your connection and try again.");
      setLoading(false);
    }
  }

  async function handleCancel() {
    setError(null);
    setLoading(true);
    try {
      const response = await fetch("/api/billing/cancel", { method: "POST" });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null;
        setError(body?.detail ?? "Something went wrong canceling your subscription.");
        setLoading(false);
        return;
      }
      window.location.reload();
    } catch {
      setError("Couldn't reach the server. Please check your connection and try again.");
      setLoading(false);
    }
  }

  if (isFreePlan) {
    return (
      <Button variant="outline" size="lg" className="w-full" disabled>
        {isCurrentPlan ? "Your current plan" : "Included"}
      </Button>
    );
  }

  return (
    <>
      <Script
        src="https://checkout.razorpay.com/v1/checkout.js"
        strategy="lazyOnload"
      />
      <div className="flex flex-col gap-2">
        <Button
          size="lg"
          variant={isCurrentPlan ? "outline" : "default"}
          className="w-full"
          onClick={isCurrentPlan ? handleCancel : handleSubscribe}
          disabled={loading}
        >
          {loading && <Loader2 className="h-4 w-4 animate-spin" />}
          {isCurrentPlan ? "Cancel subscription" : "Upgrade to Pro"}
        </Button>
        {error && <p className="text-xs text-risk-foreground">{error}</p>}
      </div>
    </>
  );
}
