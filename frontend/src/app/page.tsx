'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import StationSelector from '../components/StationSelector';
import NavigationInput from '../components/NavigationInput';
import NavigationResults from '../components/NavigationResults';
import { NavigateResponse, RouteSegment, TurnPoint } from '../types';

// Leaflet needs window, so load the map only on client side
const RouteMap = dynamic(() => import('../components/RouteMap'), { ssr: false });

export default function Home() {
  const [selectedZoneID, setSelectedZoneID] = useState('');
  const [handicapped, setHandicapped] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [instructions, setInstructions] = useState<string[]>([]);
  const [route, setRoute] = useState<RouteSegment[]>([]);
  const [turnPoints, setTurnPoints] = useState<TurnPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(query: string) {
    setIsLoading(true);
    setInstructions([]);
    setRoute([]);
    setTurnPoints([]);
    setError(null);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 60000);

    try {
      const response = await fetch('/api/navigate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zoneID: selectedZoneID, query, handicapped }),
        signal: controller.signal,
      });

      const data: NavigateResponse = await response.json();

      if (data.error) {
        setError(data.error);
        setInstructions([]);
        setRoute([]);
        setTurnPoints([]);
      } else if (data.instructions.length === 0) {
        setError('Keine Navigationsanweisungen verfügbar');
        setInstructions([]);
        setRoute([]);
        setTurnPoints([]);
      } else {
        setInstructions(data.instructions);
        setRoute(data.route || []);
        setTurnPoints(data.turn_points || []);
        setError(null);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setError('Anfrage hat zu lange gedauert. Bitte versuchen Sie es erneut.');
      } else {
        setError('Verbindung zum Server fehlgeschlagen. Bitte versuchen Sie es erneut.');
      }
      setInstructions([]);
      setRoute([]);
      setTurnPoints([]);
    } finally {
      clearTimeout(timeoutId);
      setIsLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex flex-col items-center p-4">
      <div className="w-full max-w-2xl space-y-6 mt-8">
        <h1 className="text-3xl font-bold text-center">
          DB Indoor Navigation
        </h1>
        <p className="text-center text-gray-600 mb-4">
          Navigieren Sie innerhalb von Bahnhöfen mit natürlicher Sprache.
        </p>

        <StationSelector
          onStationChange={setSelectedZoneID}
          selectedZoneID={selectedZoneID}
        />

        <NavigationInput
          zoneID={selectedZoneID}
          onSubmit={handleSubmit}
          isLoading={isLoading}
        />

        <div className="flex items-center gap-3">
          <label htmlFor="handicapped-toggle" className="text-sm font-medium cursor-pointer">
            Barrierefreie Route
          </label>
          <button
            id="handicapped-toggle"
            role="switch"
            type="button"
            aria-checked={handicapped}
            onClick={() => setHandicapped(!handicapped)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${
              handicapped ? 'bg-blue-600' : 'bg-gray-300'
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                handicapped ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        <RouteMap route={route} turnPoints={turnPoints} />

        <NavigationResults
          instructions={instructions}
          error={error}
          isLoading={isLoading}
        />
      </div>
    </main>
  );
}
