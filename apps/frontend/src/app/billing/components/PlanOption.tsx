"use client";

import { FiCheck, FiLoader } from "react-icons/fi";

interface PlanOptionProps {
  name: string;
  price: string;
  period: string;
  pricePerMonth?: string;
  features: string[];
  onSubscribe: () => void;
  isLoading: boolean;
  disabled: boolean;
  featured?: boolean;
  featuredLabel?: string;
}

export function PlanOption({
  name,
  price,
  period,
  pricePerMonth,
  features,
  onSubscribe,
  isLoading,
  disabled,
  featured = false,
  featuredLabel,
}: PlanOptionProps) {
  const borderClass = featured
    ? "border-2 border-deep-indigo-400"
    : "border border-gray-200 hover:border-deep-indigo-400 transition-colors";

  return (
    <div className={`rounded-lg p-6 relative ${borderClass}`}>
      {featured && featuredLabel && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2">
          <span className="bg-deep-indigo-400 text-white px-3 py-1 rounded-full text-xs font-semibold">
            {featuredLabel}
          </span>
        </div>
      )}

      <div className="mb-4">
        <h3 className="text-lg font-semibold text-gray-900">{name}</h3>
        <div className="flex items-baseline mt-2">
          <span className="text-3xl font-bold text-gray-900">{price}</span>
          <span className="text-gray-600 ml-2">/{period}</span>
        </div>
        {pricePerMonth && (
          <p className="text-sm text-gray-500 mt-1">{pricePerMonth}</p>
        )}
      </div>

      <ul className="space-y-3 mb-6">
        {features.map((feature, index) => (
          <li key={index} className="flex items-start gap-2">
            <FiCheck className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            <span className="text-sm text-gray-600">{feature}</span>
          </li>
        ))}
      </ul>

      <button
        onClick={onSubscribe}
        disabled={disabled}
        className="btn-base btn-md w-full bg-deep-indigo-400 text-white hover:bg-deep-indigo-500 disabled:opacity-50"
      >
        {isLoading ? (
          <FiLoader className="w-5 h-5 animate-spin mx-auto" />
        ) : (
          `Subscribe ${name}`
        )}
      </button>
    </div>
  );
}
