export interface NavigateRequest {
  zoneID: string;
  query: string;
  handicapped: boolean;
  image?: string;
  image_media_type?: string;
}

export interface RoutePoint {
  lat: number;
  lon: number;
}

export interface RouteSegment {
  segment_type: string;
  level: string;
  points: RoutePoint[];
  simplified_points: RoutePoint[];
}

export interface TurnPoint {
  lat: number;
  lon: number;
  angle_change: number;
  poi_name: string | null;
}

export interface NavigateResponse {
  instructions: string[];
  route: RouteSegment[];
  turn_points: TurnPoint[];
  start_inside: boolean;
  end_inside: boolean;
  error?: string;
}

export interface StationListResponse {
  stations: Array<{
    zoneID: string;
    name: string;
  }>;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  image?: string;
  instructions?: string[];
  route?: RouteSegment[];
  turnPoints?: TurnPoint[];
  startInside?: boolean;
  endInside?: boolean;
  error?: string;
  isLoading?: boolean;
}
