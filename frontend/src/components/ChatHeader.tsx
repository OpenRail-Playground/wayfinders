'use client';

import { useEffect, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { StationListResponse } from '../types';

interface ChatHeaderProps {
  selectedZoneID: string;
  selectedStationName: string;
  handicapped: boolean;
  onStationChange: (zoneID: string, name: string) => void;
  onHandicappedChange: (value: boolean) => void;
}

export default function ChatHeader({
  selectedZoneID,
  selectedStationName,
  handicapped,
  onStationChange,
  onHandicappedChange,
}: ChatHeaderProps) {
  const [stations, setStations] = useState<StationListResponse['stations']>([]);
  const [showSelector, setShowSelector] = useState(false);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    async function fetchStations() {
      try {
        const response = await fetch('/api/stations');
        if (!response.ok) throw new Error('Failed to fetch');
        const data: StationListResponse = await response.json();
        const sorted = [...data.stations].sort((a, b) =>
          a.name.localeCompare(b.name, 'de')
        );
        setStations(sorted);

        if (sorted.length > 0 && !selectedZoneID) {
          onStationChange(sorted[0].zoneID, sorted[0].name);
        }
      } catch {
        // Silent fail
      } finally {
        setLoading(false);
      }
    }
    fetchStations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filteredStations = search
    ? stations.filter(s => s.name.toLowerCase().includes(search.toLowerCase()))
    : stations;

  const closeSelector = useCallback(() => {
    setShowSelector(false);
    setSearch('');
  }, []);

  const selectorOverlay = showSelector && mounted ? createPortal(
    <div className="fixed inset-0 z-[9999] flex flex-col" style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0 }}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={closeSelector} />

      {/* Panel */}
      <div className="relative mt-auto mx-4 mb-4 max-h-[70vh] bg-white rounded-2xl shadow-2xl overflow-hidden animate-fade-in-up flex flex-col border border-[#d0d0d0]">
        {/* Title */}
        <div className="px-4 pt-4 pb-2">
          <h2 className="text-base font-bold text-[#111]">Bahnhof wählen</h2>
        </div>

        {/* Search */}
        <div className="px-4 pb-3">
          <div className="relative">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#888" strokeWidth="2.5" className="absolute left-3.5 top-1/2 -translate-y-1/2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Suchen..."
              className="w-full pl-10 pr-4 py-3 bg-[#f3f3f3] border border-[#ddd] rounded-xl text-sm text-[#111] focus:outline-none focus:ring-2 focus:ring-[#e30613]/30 focus:border-[#e30613] placeholder:text-[#888]"
              autoFocus
            />
          </div>
        </div>

        {/* Station list */}
        <div className="overflow-y-auto flex-1 border-t border-[#eee]">
          {filteredStations.length === 0 && (
            <p className="px-5 py-4 text-sm text-[#888]">Keine Ergebnisse</p>
          )}
          {filteredStations.map(station => (
            <button
              key={station.zoneID + station.name}
              onClick={() => {
                onStationChange(station.zoneID, station.name);
                closeSelector();
              }}
              className={`w-full text-left px-5 py-3.5 text-[14px] border-b border-[#f0f0f0] transition-colors active:bg-[#f5f5f5] ${
                station.zoneID === selectedZoneID && station.name === selectedStationName
                  ? 'bg-[#fef2f2] font-bold text-[#e30613]'
                  : 'text-[#222] font-medium'
              }`}
            >
              {station.name}
            </button>
          ))}
        </div>
      </div>
    </div>,
    document.body
  ) : null;

  return (
    <>
      <header className="sticky top-0 z-50 safe-top">
        {/* Main header bar */}
        <div className="bg-[#e30613] px-4 py-3.5 flex items-center justify-between shadow-md">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-white/20 rounded-full flex items-center justify-center">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="3 11 22 2 13 21 11 13 3 11" />
              </svg>
            </div>
            <div>
              <h1 className="text-white font-bold text-[15px] leading-tight">Station Wayfinder</h1>
            </div>
          </div>

          <button
            onClick={() => onHandicappedChange(!handicapped)}
            className={`w-9 h-9 rounded-full flex items-center justify-center transition-all ${
              handicapped
                ? 'bg-white text-[#e30613] shadow-md'
                : 'bg-white/20 text-white hover:bg-white/30'
            }`}
            aria-label={handicapped ? 'Barrierefreie Route aktiv' : 'Barrierefreie Route'}
            title={handicapped ? 'Barrierefreie Route aktiv' : 'Barrierefreie Route'}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2a2 2 0 1 1 0 4 2 2 0 0 1 0-4Zm3.5 7h-3l-.5-2h-1l-.5 2h-3a.5.5 0 0 0 0 1h2.5l-1.5 5-2.5 3.5a.75.75 0 0 0 1.2.9L9 14.5l1.5-2 2 4.5v4a.75.75 0 0 0 1.5 0v-4.5l-1.8-4.5L13.5 10h2a.5.5 0 0 0 0-1Z"/>
            </svg>
          </button>
        </div>

        {/* Station selector */}
        <div className="bg-white border-b-2 border-[#e0e0e0] px-4 py-2.5">
          <button
            onClick={() => setShowSelector(true)}
            className="w-full flex items-center gap-3 px-4 py-3 bg-[#f7f7f7] border border-[#d0d0d0] rounded-xl transition-all active:scale-[0.98] hover:border-[#bbb]"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#e30613" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0">
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
              <circle cx="12" cy="10" r="3" />
            </svg>
            <span className={`flex-1 text-left text-[14px] ${selectedStationName ? 'font-bold text-[#111]' : 'text-[#888] font-medium'}`}>
              {loading ? 'Lade Stationen...' : selectedStationName || 'Bahnhof wählen'}
            </span>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#555" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
        </div>
      </header>

      {selectorOverlay}
    </>
  );
}
