'use client';

import { useState } from 'react';

interface NavigationInputProps {
  zoneID: string;
  onSubmit: (query: string) => void;
  isLoading?: boolean;
}

export default function NavigationInput({
  zoneID,
  onSubmit,
  isLoading = false,
}: NavigationInputProps) {
  const [query, setQuery] = useState('');
  const [validationMessage, setValidationMessage] = useState('');

  const isQueryEmpty = query.trim().length === 0;
  const isStationMissing = zoneID === '';
  const isSubmitDisabled = isStationMissing || isQueryEmpty || isLoading;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (isQueryEmpty) {
      setValidationMessage('Bitte geben Sie eine Beschreibung ein');
      return;
    }

    if (isStationMissing) {
      setValidationMessage('Bitte wählen Sie einen Bahnhof');
      return;
    }

    setValidationMessage('');
    onSubmit(query.trim());
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    setQuery(e.target.value);
    if (validationMessage) {
      setValidationMessage('');
    }
  }

  return (
    <form onSubmit={handleSubmit} className="w-full" noValidate>
      <div className="flex flex-col gap-2">
        <label htmlFor="navigation-query" className="text-sm font-medium">
          Wohin möchten Sie navigieren?
        </label>
        <div className="flex gap-2">
          <input
            id="navigation-query"
            type="text"
            value={query}
            onChange={handleInputChange}
            maxLength={500}
            placeholder="z.B. Ich bin am Gleis 5 und möchte zum Starbucks"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            aria-describedby="validation-message"
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={isSubmitDisabled}
            className="min-w-[44px] min-h-[44px] px-4 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? 'Lädt...' : 'Navigieren'}
          </button>
        </div>
        <div
          id="validation-message"
          aria-live="polite"
          className="min-h-[1.25rem] text-sm text-red-600"
        >
          {validationMessage}
        </div>
      </div>
    </form>
  );
}
