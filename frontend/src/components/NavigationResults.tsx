'use client';

import { useEffect, useRef, useState } from 'react';

interface NavigationResultsProps {
  instructions: string[];
  error: string | null;
  isLoading: boolean;
}

export default function NavigationResults({
  instructions,
  error,
  isLoading,
}: NavigationResultsProps) {
  const [timedOut, setTimedOut] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isLoading) {
      setTimedOut(false);
      timerRef.current = setTimeout(() => {
        setTimedOut(true);
      }, 60000);
    } else {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      setTimedOut(false);
    }

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [isLoading]);

  // Timeout state: show timeout error
  if (timedOut) {
    return (
      <div
        role="alert"
        className="w-full max-w-full overflow-x-hidden p-4 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm break-words"
      >
        Anfrage hat zu lange gedauert. Bitte versuchen Sie es erneut.
      </div>
    );
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="w-full max-w-full overflow-x-hidden flex items-center gap-3 p-4" aria-busy="true" aria-live="polite">
        <svg
          className="animate-spin h-5 w-5 text-blue-600 shrink-0"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
        <span className="text-sm text-gray-600">Navigation wird berechnet...</span>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div
        role="alert"
        className="w-full max-w-full overflow-x-hidden p-4 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm break-words"
      >
        {error}
      </div>
    );
  }

  // Empty instructions treated as error (response received but no instructions)
  if (instructions.length === 0) {
    return null;
  }

  // Success state: render instructions as numbered list
  return (
    <div className="w-full max-w-full overflow-x-hidden">
      <ol className="list-decimal list-inside space-y-2">
        {instructions.map((instruction, index) => (
          <li
            key={index}
            className="min-h-[44px] min-w-[44px] p-3 bg-white border border-gray-200 rounded-md text-sm leading-relaxed break-words"
          >
            {instruction}
          </li>
        ))}
      </ol>
    </div>
  );
}
