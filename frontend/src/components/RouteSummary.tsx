'use client';

import { RouteSegment } from '../types';

interface RouteSummaryProps {
  route: RouteSegment[];
  instructions: string[];
  startInside?: boolean;
  endInside?: boolean;
}

const LEVEL_NAMES: Record<string, string> = {
  BASEMENT_FLOOR_4: 'UG4',
  BASEMENT_FLOOR_3: 'UG3',
  BASEMENT_FLOOR_2: 'UG2',
  BASEMENT_FLOOR_1: 'UG1',
  GROUND_FLOOR: 'EG',
  UPPER_FLOOR_1: 'OG1',
  UPPER_FLOOR_2: 'OG2',
  UPPER_FLOOR_3: 'OG3',
};

const LEVEL_FULL_NAMES: Record<string, string> = {
  BASEMENT_FLOOR_4: 'Untergeschoss 4',
  BASEMENT_FLOOR_3: 'Untergeschoss 3',
  BASEMENT_FLOOR_2: 'Untergeschoss 2',
  BASEMENT_FLOOR_1: 'Untergeschoss 1',
  GROUND_FLOOR: 'Erdgeschoss',
  UPPER_FLOOR_1: 'Obergeschoss 1',
  UPPER_FLOOR_2: 'Obergeschoss 2',
  UPPER_FLOOR_3: 'Obergeschoss 3',
};

const LEVEL_ORDER: Record<string, number> = {
  BASEMENT_FLOOR_4: -4,
  BASEMENT_FLOOR_3: -3,
  BASEMENT_FLOOR_2: -2,
  BASEMENT_FLOOR_1: -1,
  GROUND_FLOOR: 0,
  UPPER_FLOOR_1: 1,
  UPPER_FLOOR_2: 2,
  UPPER_FLOOR_3: 3,
};

function displayLevel(level: string): string {
  return LEVEL_NAMES[level] || level;
}

function displayLevelFull(level: string): string {
  return LEVEL_FULL_NAMES[level] || level;
}

function extractLevels(route: RouteSegment[]): string[] {
  const levels: string[] = [];
  for (const seg of route) {
    if (levels.length === 0 || levels[levels.length - 1] !== seg.level) {
      levels.push(seg.level);
    }
  }
  return levels;
}

function estimateDistance(instructions: string[]): number {
  let total = 0;
  for (const instr of instructions) {
    const match = instr.match(/(\d+)\s*Meter/i);
    if (match) {
      total += parseInt(match[1], 10);
    }
  }
  return total;
}

function countLevelChanges(route: RouteSegment[]): number {
  let changes = 0;
  for (const seg of route) {
    if (seg.segment_type !== 'WALK') {
      changes++;
    }
  }
  return changes;
}

function getDirection(levels: string[]): 'up' | 'down' | 'same' | 'mixed' {
  if (levels.length <= 1) return 'same';
  const first = LEVEL_ORDER[levels[0]] ?? 0;
  const last = LEVEL_ORDER[levels[levels.length - 1]] ?? 0;
  if (last > first) return 'up';
  if (last < first) return 'down';
  return 'same';
}

function buildTextSummary(
  route: RouteSegment[],
  instructions: string[],
  levels: string[],
  distance: number,
  levelChanges: number,
  startInside: boolean,
  endInside: boolean,
): string {
  const startLevel = levels[0];
  const endLevel = levels[levels.length - 1];
  const sameLevel = startLevel === endLevel;

  // Extract transport types used
  const transports = new Set<string>();
  for (const seg of route) {
    if (seg.segment_type === 'ESCALATOR') transports.add('Rolltreppe');
    if (seg.segment_type === 'ELEVATOR') transports.add('Aufzug');
    if (seg.segment_type === 'STAIRS') transports.add('Treppe');
    if (seg.segment_type === 'RAMP') transports.add('Rampe');
  }

  // Try to extract destination from last instruction
  let destination = '';
  if (instructions.length > 0) {
    const lastInstr = instructions[instructions.length - 1];
    const richtungMatch = lastInstr.match(/Richtung\s+(.+?)[\.\,]/);
    const zumMatch = lastInstr.match(/(?:zum|zur|bis)\s+(.+?)[\.\,]?$/i);
    if (richtungMatch) destination = richtungMatch[1];
    else if (zumMatch) destination = zumMatch[1];
  }

  // Determine inside/outside transitions from backend data
  const goesOutside = startInside && !endInside;
  const comesFromOutside = !startInside && endInside;

  // Build summary
  let summary = '';

  if (goesOutside) {
    // Leaving building
    if (sameLevel) {
      summary = `Vom ${displayLevelFull(startLevel)} nach draußen`;
    } else {
      summary = `Vom ${displayLevelFull(startLevel)} nach draußen (${displayLevelFull(endLevel)})`;
    }
    if (destination) summary += ` · ${destination}`;
    if (transports.size > 0) summary += ` · ${[...transports].join(' & ')}`;
  } else if (comesFromOutside) {
    // Entering building
    summary = `Von draußen ins ${displayLevelFull(endLevel)}`;
    if (destination) summary += ` · ${destination}`;
    if (transports.size > 0) summary += ` · ${[...transports].join(' & ')}`;
  } else if (sameLevel) {
    // Same level, staying inside
    summary = `Ca. ${distance}m im ${displayLevelFull(startLevel)}`;
    if (destination) summary += ` Richtung ${destination}`;
  } else {
    // Level change within building
    const dir = LEVEL_ORDER[endLevel]! < LEVEL_ORDER[startLevel]! ? 'runter' : 'hoch';
    summary = `Vom ${displayLevelFull(startLevel)} ${dir} ins ${displayLevelFull(endLevel)}`;
    if (destination) summary += ` · ${destination}`;
    if (transports.size > 0) {
      summary += ` · ${[...transports].join(' & ')}`;
    }
  }

  return summary;
}

export default function RouteSummary({ route, instructions, startInside, endInside }: RouteSummaryProps) {
  if (!route || route.length === 0) return null;

  const levels = extractLevels(route);
  const startLevel = levels[0];
  const endLevel = levels[levels.length - 1];
  const distance = estimateDistance(instructions);
  const levelChanges = countLevelChanges(route);
  const direction = getDirection(levels);
  const textSummary = buildTextSummary(route, instructions, levels, distance, levelChanges, startInside ?? true, endInside ?? true);
  const sameLevel = startLevel === endLevel;

  const directionIcon = direction === 'up' ? '↑' : direction === 'down' ? '↓' : direction === 'mixed' ? '↕' : '→';

  return (
    <div className="border-b border-[#eee]">
      {/* Textual summary */}
      <div className="px-4 pt-3 pb-2">
        <p className="text-[13px] text-[#333] font-semibold leading-snug">{textSummary}</p>
      </div>

      {/* Badge row */}
      <div className="flex items-center gap-2 px-4 pb-3">
        {/* Level transition badges - only if levels change */}
        {!sameLevel && (
          <div className="flex items-center gap-1.5">
            <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-[#e30613] text-white text-[11px] font-bold">
              {displayLevel(startLevel)}
            </span>
            <span className="text-[#999] text-sm">{directionIcon}</span>
            <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-[#222] text-white text-[11px] font-bold">
              {displayLevel(endLevel)}
            </span>
          </div>
        )}

        <div className={`flex items-center gap-2 text-[11px] text-[#666] font-medium ${sameLevel ? '' : 'ml-auto'}`}>
          {distance > 0 && (
            <span>~{distance}m</span>
          )}
          {levelChanges > 0 && (
            <span className="flex items-center gap-0.5">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
              {levelChanges}×
            </span>
          )}
          <span>{instructions.length} Schritte</span>
        </div>
      </div>
    </div>
  );
}
