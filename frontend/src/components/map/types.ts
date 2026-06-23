export interface MapMarker {
  id: string
  latitude: number
  longitude: number
  title?: string
  description?: string
  icon?: string
  color?: string
  popup?: boolean
}

export interface MapProps {
  center?: { latitude: number; longitude: number }
  zoom?: number
  markers?: MapMarker[]
  height?: string | number
  width?: string | number
  showZoomControls?: boolean
  showLayerControls?: boolean
  showScale?: boolean
  draggable?: boolean
  scrollZoom?: boolean
  onMarkerClick?: (marker: MapMarker) => void
  onMapClick?: (event: { latitude: number; longitude: number }) => void
  onZoomChange?: (zoom: number) => void
  onCenterChange?: (center: { latitude: number; longitude: number }) => void
}
