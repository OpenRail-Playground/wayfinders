'use client';

import { useEffect, useState } from 'react';
import { StationListResponse } from '../types';

interface StationSelectorProps {
  onStationChange: (zoneID: string) => void;
  selectedZoneID?: string;
}

export default function StationSelector({
  onStationChange,
  selectedZoneID,
}: StationSelectorProps) {
  const [stations, setStations] = useState<
    StationListResponse['stations']
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchStations() {
      try {
        const response = await fetch('/api/stations');
        if (!response.ok) {
          throw new Error(
            `Stationen konnten nicht geladen werden (${response.status})`
          );
        }
        const data: StationListResponse = await response.json();
        const sorted = [...data.stations].sort((a, b) =>
          a.name.localeCompare(b.name, 'de')
        );
        setStations(sorted);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : 'Stationen konnten nicht geladen werden'
        );
      } finally {
        setLoading(false);
      }
    }

    fetchStations();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2" role="status">
        <svg
          className="animate-spin h-5 w-5 text-gray-500"
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
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
        <span className="text-sm text-gray-500">Lade Stationen…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
        <select
          disabled
          className="w-full p-2 border border-gray-300 rounded bg-gray-100 text-gray-400 cursor-not-allowed"
          aria-label="Bahnhof auswählen"
        >
          <option>Bahnhof auswählen…</option>
        </select>
      </div>
    );
  }

  return (
    <select
      value={selectedZoneID ?? ''}
      onChange={(e) => onStationChange(e.target.value)}
      className="w-full p-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
      aria-label="Bahnhof auswählen"
    >
      <option value="" disabled>
        Bahnhof auswählen…
      </option>
      {stations.map((station) => (
        <option key={station.zoneID} value={station.zoneID}>
          {station.name}
        </option>
      ))}
    </select>
  );
}
