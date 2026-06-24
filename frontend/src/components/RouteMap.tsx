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

    const map = L.map(mapRef.current, {
      zoomControl: false,
      attributionControl: false,
    });
    mapInstanceRef.current = map;

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 22,
    }).addTo(map);

    // Draw original path (thin, light)
    route.forEach((seg) => {
      const latlngs: L.LatLngExpression[] = seg.points.map((p) => [p.lat, p.lon]);
      L.polyline(latlngs, {
        color: '#94a3b8',
        weight: 5,
        opacity: 0.4,
      }).addTo(map);
    });

    // Draw simplified path (bold, colored)
    route.forEach((seg) => {
      const pts = seg.simplified_points.length > 0 ? seg.simplified_points : seg.points;
      const latlngs: L.LatLngExpression[] = pts.map((p) => [p.lat, p.lon]);
      L.polyline(latlngs, {
        color: '#e30613',
        weight: 3,
        opacity: 1,
        dashArray: '8, 6',
      }).addTo(map);
    });

    // Turn points
    turnPoints.forEach((tp) => {
      L.circleMarker([tp.lat, tp.lon], {
        radius: 6,
        fillColor: '#f97316',
        color: '#fff',
        weight: 2,
        fillOpacity: 1,
      })
        .bindTooltip(
          `${tp.poi_name || 'Abbiegen'} (${tp.angle_change.toFixed(0)}°)`,
          { direction: 'top' }
        )
        .addTo(map);
    });

    // Start marker
    const firstPoint = route[0].points[0];
    L.circleMarker([firstPoint.lat, firstPoint.lon], {
      radius: 7,
      fillColor: '#16a34a',
      color: '#fff',
      weight: 2,
      fillOpacity: 1,
    })
      .bindTooltip('Start', { permanent: true, direction: 'top', className: 'map-tooltip' })
      .addTo(map);

    // End marker
    const lastSeg = route[route.length - 1];
    const lastPoint = lastSeg.points[lastSeg.points.length - 1];
    L.circleMarker([lastPoint.lat, lastPoint.lon], {
      radius: 7,
      fillColor: '#e30613',
      color: '#fff',
      weight: 2,
      fillOpacity: 1,
    })
      .bindTooltip('Ziel', { permanent: true, direction: 'top', className: 'map-tooltip' })
      .addTo(map);

    // Fit map to bounds
    const bounds = L.latLngBounds(allPoints);
    map.fitBounds(bounds, { padding: [25, 25] });

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, [route, turnPoints]);

  if (route.length === 0) return null;

  return (
    <div ref={mapRef} style={{ height: '220px', width: '100%' }} />
  );
}
