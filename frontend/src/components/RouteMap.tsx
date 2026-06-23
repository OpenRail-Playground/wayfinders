'use client';

import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { RouteSegment, TurnPoint } from '../types';

interface RouteMapProps {
  route: RouteSegment[];
  turnPoints?: TurnPoint[];
}

export default function RouteMap({ route, turnPoints = [] }: RouteMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!mapRef.current || route.length === 0) return;

    // Clean up previous map
    if (mapInstanceRef.current) {
      mapInstanceRef.current.remove();
      mapInstanceRef.current = null;
    }

    // Collect all points to compute bounds
    const allPoints: L.LatLngExpression[] = [];
    route.forEach((seg) => {
      seg.points.forEach((p) => allPoints.push([p.lat, p.lon]));
    });

    if (allPoints.length === 0) return;

    const map = L.map(mapRef.current);
    mapInstanceRef.current = map;

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 22,
    }).addTo(map);

    // Draw original path (thin, light gray)
    route.forEach((seg) => {
      const latlngs: L.LatLngExpression[] = seg.points.map((p) => [p.lat, p.lon]);
      L.polyline(latlngs, {
        color: '#9ca3af',
        weight: 6,
        opacity: 0.5,
      }).addTo(map);
    });

    // Draw simplified path (bold, colored)
    route.forEach((seg) => {
      const pts = seg.simplified_points.length > 0 ? seg.simplified_points : seg.points;
      const latlngs: L.LatLngExpression[] = pts.map((p) => [p.lat, p.lon]);
      L.polyline(latlngs, {
        color: '#2563eb',
        weight: 3,
        opacity: 1,
        dashArray: '8, 6',
      }).addTo(map);
    });

    // Draw turn points as orange markers
    turnPoints.forEach((tp) => {
      L.circleMarker([tp.lat, tp.lon], {
        radius: 7,
        fillColor: '#f97316',
        color: '#fff',
        weight: 2,
        fillOpacity: 1,
      })
        .bindTooltip(
          `${tp.poi_name || 'Turn'} (${tp.angle_change.toFixed(0)}°)`,
          { direction: 'top' }
        )
        .addTo(map);
    });

    // Add start marker
    const firstPoint = route[0].points[0];
    L.circleMarker([firstPoint.lat, firstPoint.lon], {
      radius: 8,
      fillColor: '#16a34a',
      color: '#fff',
      weight: 2,
      fillOpacity: 1,
    })
      .bindTooltip('Start', { permanent: true, direction: 'top' })
      .addTo(map);

    // Add end marker
    const lastSeg = route[route.length - 1];
    const lastPoint = lastSeg.points[lastSeg.points.length - 1];
    L.circleMarker([lastPoint.lat, lastPoint.lon], {
      radius: 8,
      fillColor: '#dc2626',
      color: '#fff',
      weight: 2,
      fillOpacity: 1,
    })
      .bindTooltip('Ziel', { permanent: true, direction: 'top' })
      .addTo(map);

    // Fit map to route bounds
    const bounds = L.latLngBounds(allPoints);
    map.fitBounds(bounds, { padding: [30, 30] });

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, [route, turnPoints]);

  if (route.length === 0) return null;

  return (
    <div className="w-full space-y-2">
      <div className="flex gap-4 text-xs text-gray-600">
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 h-1 bg-gray-400 opacity-50"></span> Original
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 h-0.5 bg-blue-600 border-dashed"></span> Simplified
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded-full bg-orange-500"></span> Turn
        </span>
      </div>
      <div ref={mapRef} style={{ height: '350px', width: '100%' }} className="rounded-md border border-gray-200" />
    </div>
  );
}
