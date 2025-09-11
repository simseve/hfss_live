# Tile System API Changes - Frontend Developer Guide

## Overview
We've implemented a new tile-based WebSocket system that runs in parallel with the existing point-based system. This guide details all API changes for frontend refactoring.

## 1. WebSocket Endpoint Changes

### Old System
```
URL: wss://api.hikeandfly.app/tracking/ws/track/{race_id}
Query params: ?token={token}&client_id={client_id}
```

### New System
```
URL: wss://api.hikeandfly.app/live/ws/live/{race_id}
Query params: ?token={token}&client_id={client_id}
```

## 2. Message Types - What Changed

### REMOVED Message Types
These message types NO LONGER EXIST in the new system:

```javascript
// ❌ OLD - No longer sent
{
  "type": "initial_data",
  "flights": [...],
  "tasks": [...],
  "active_viewers": 5
}

// ❌ OLD - No longer sent
{
  "type": "track_update",
  "flight": {
    "pilot_id": "123",
    "position": {...}
  }
}
```

### NEW Message Types

#### 2.1 Race Configuration (Sent on Connect)
```javascript
// ✅ NEW - Sent immediately after connection
{
  "type": "race_config",
  "race_id": "68aadbb85da525060edaaebf",
  "race_name": "HFSS App Testing",
  "timezone": "Europe/Rome",
  "delay_seconds": 60,        // 60-second broadcast delay
  "update_interval": 10,       // New data every 10 seconds
  "interpolation_rate": 1,     // Frontend should update every 1 second
  "protocol_version": "2.0",
  "features": {
    "delta_updates": true,
    "compressed_tiles": true,
    "clustering": true,
    "smooth_interpolation": true
  }
}
```

#### 2.2 Viewer Count
```javascript
// ✅ NEW - Periodic updates
{
  "type": "viewer_count",
  "count": 12,
  "timestamp": "2025-01-09T12:00:00Z"
}
```

#### 2.3 Tile Data (MVT Format)
```javascript
// ✅ NEW - Mapbox Vector Tile data
{
  "type": "tile_data",
  "tile": {"z": 12, "x": 2148, "y": 1458},
  "format": "mvt",
  "compression": "gzip",
  "data": "H4sIAAAAAAAA...",  // Base64 encoded, gzipped MVT
  "timestamp": "2025-01-09T12:00:00Z"
}
```

#### 2.4 Delta Updates (Main Position Updates)
```javascript
// ✅ NEW - Sent every 10 seconds with all pilot positions
{
  "type": "delta_update",
  "race_id": "68aadbb85da525060edaaebf",
  "data": "H4sIAAAAAAAA...",  // Base64 encoded, gzipped JSON
  "timestamp": "2025-01-09T12:00:00Z",
  "compression": "gzip",
  "update_count": 5
}

// When decompressed, the data contains:
{
  "type": "delta",
  "timestamp": "2025-01-09T12:00:00Z",
  "updates": [
    {
      "pilot_id": "abc123",
      "pilot_name": "John Doe",
      "lat": 45.123456,
      "lon": 8.123456,
      "elevation": 1234,
      "timestamp": "2025-01-09T11:59:00Z",  // 60 seconds delayed
      "x_mercator": 943842.5,   // Pre-calculated for map projection
      "y_mercator": 5683920.1
    },
    // ... more pilots
  ]
}
```

#### 2.5 Heartbeat
```javascript
// ✅ NEW - Keep-alive message
{
  "type": "heartbeat",
  "timestamp": "2025-01-09T12:00:00Z"
}
```

## 3. Client-to-Server Messages

### Messages You MUST Send

#### 3.1 Viewport Update (REQUIRED)
Send whenever the map moves or zooms:
```javascript
{
  "type": "viewport_update",
  "viewport": {
    "tiles": [
      [12, 2148, 1458],  // [zoom, x, y]
      [12, 2148, 1459],
      [12, 2149, 1458],
      [12, 2149, 1459]
    ]
  }
}
```

#### 3.2 Request Initial Data (OPTIONAL)
Send after connection to get initial tiles:
```javascript
{
  "type": "request_initial_data",
  "zoom": 12,
  "bbox": [-42.0, -21.0, 9.0, 46.0]  // [minLon, minLat, maxLon, maxLat]
}
```

#### 3.3 Ping (OPTIONAL)
Keep connection alive:
```javascript
{
  "type": "ping",
  "timestamp": "2025-01-09T12:00:00Z"
}
```

#### 3.4 Get Stats (OPTIONAL)
Request performance statistics:
```javascript
{
  "type": "get_stats"
}

// Response:
{
  "type": "stats",
  "data": {
    "viewers": 12,
    "tiles_cached": 45,
    "client_id": "client_abc123",
    "timestamp": "2025-01-09T12:00:00Z"
  }
}
```

## 4. Data Flow Changes

### Old System Flow
```
1. Connect → Receive initial_data with all pilots
2. Receive track_update for each pilot movement
3. Update pilot positions directly
```

### New System Flow
```
1. Connect → Receive race_config
2. Send viewport_update with visible tiles
3. Receive tile_data for visible areas (optional, for MVT rendering)
4. Receive delta_update every 10 seconds with ALL pilot positions
5. Interpolate positions smoothly over 10 seconds (1-second updates)
```

## 5. Key Implementation Changes

### 5.1 Decompression Required
Delta updates are gzip compressed. You MUST decompress:

```javascript
// Using pako.js library
function decompressDelta(base64Data) {
  // Decode base64
  const binaryString = atob(base64Data);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  
  // Decompress with pako
  const decompressed = pako.inflate(bytes, { to: 'string' });
  return JSON.parse(decompressed);
}
```

### 5.2 Interpolation Required
Updates arrive every 10 seconds. You MUST interpolate for smooth movement:

```javascript
// Positions at T=0 and T=10
// Interpolate every second for smooth movement
function interpolatePosition(oldPos, newPos, progress) {
  return {
    lat: oldPos.lat + (newPos.lat - oldPos.lat) * progress,
    lon: oldPos.lon + (newPos.lon - oldPos.lon) * progress
  };
}

// Update every second
let step = 0;
const timer = setInterval(() => {
  step++;
  const progress = step / 10;  // 0.1, 0.2, ... 1.0
  const currentPos = interpolatePosition(oldPos, newPos, progress);
  updateMarkerPosition(currentPos);
  
  if (step >= 10) clearInterval(timer);
}, 1000);
```

### 5.3 Viewport Management
You MUST track viewport and request visible tiles:

```javascript
// Calculate tile coordinates for current view
function getTilesInViewport(map) {
  const bounds = map.getBounds();
  const zoom = Math.floor(map.getZoom());
  const tiles = [];
  
  const minTile = latLngToTile(bounds.getSouth(), bounds.getWest(), zoom);
  const maxTile = latLngToTile(bounds.getNorth(), bounds.getEast(), zoom);
  
  for (let x = minTile.x; x <= maxTile.x; x++) {
    for (let y = minTile.y; y <= maxTile.y; y++) {
      tiles.push([zoom, x, y]);
    }
  }
  return tiles;
}

function latLngToTile(lat, lng, zoom) {
  const n = Math.pow(2, zoom);
  const x = Math.floor((lng + 180) / 360 * n);
  const y = Math.floor((1 - Math.log(Math.tan(lat * Math.PI / 180) + 
           1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2 * n);
  return { x, y };
}
```

## 6. Performance Improvements

### Bandwidth Reduction
- **Old**: Full pilot data for each update
- **New**: Compressed deltas only
- **Savings**: ~60-70% bandwidth reduction

### Update Frequency
- **Old**: Variable, potentially overwhelming
- **New**: Predictable 10-second intervals
- **Interpolation**: Smooth 1-second visual updates

### Scalability
- **Old**: O(n) where n = number of viewers
- **New**: O(1) tile generation, cached for all viewers

## 7. Migration Checklist

- [ ] Update WebSocket URL from `/tracking/ws/track/` to `/live/ws/live/`
- [ ] Remove handlers for `initial_data` and `track_update`
- [ ] Add handlers for `race_config`, `delta_update`, `tile_data`
- [ ] Implement gzip decompression (add pako.js or similar)
- [ ] Implement 10-second → 1-second interpolation
- [ ] Add viewport tracking and `viewport_update` messages
- [ ] Handle 60-second delay (positions are 1 minute behind real-time)
- [ ] Update connection status handling
- [ ] Add viewer count display

## 8. Libraries Required

```html
<!-- For gzip decompression -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js"></script>

<!-- For MVT tile rendering (optional) -->
<script src="https://unpkg.com/leaflet.vectorgrid@1.3.0/dist/Leaflet.VectorGrid.bundled.js"></script>
```

## 9. Backwards Compatibility

Both systems run in parallel:
- Old endpoint: Still active at `/tracking/ws/track/{race_id}`
- New endpoint: Available at `/live/ws/live/{race_id}`
- Same authentication token works for both
- Can switch between systems without data loss

## 10. Example Implementation

```javascript
class TileSystemClient {
  constructor(raceId, token) {
    this.ws = new WebSocket(
      `wss://api.hikeandfly.app/live/ws/live/${raceId}?token=${token}&client_id=${clientId}`
    );
    
    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      
      switch(msg.type) {
        case 'delta_update':
          this.processDelta(msg);
          break;
        case 'race_config':
          this.updateInterval = msg.update_interval;
          this.delaySeconds = msg.delay_seconds;
          break;
      }
    };
  }
  
  processDelta(msg) {
    // Decompress
    const data = this.decompress(msg.data);
    
    // Update each pilot with interpolation
    data.updates.forEach(pilot => {
      this.interpolatePilot(pilot);
    });
  }
  
  interpolatePilot(newData) {
    const oldPos = this.pilots.get(newData.pilot_id);
    let step = 0;
    
    const timer = setInterval(() => {
      step++;
      const progress = step / this.updateInterval;
      
      const lat = oldPos.lat + (newData.lat - oldPos.lat) * progress;
      const lon = oldPos.lon + (newData.lon - oldPos.lon) * progress;
      
      this.updateMarker(newData.pilot_id, { lat, lon });
      
      if (step >= this.updateInterval) {
        clearInterval(timer);
        this.pilots.set(newData.pilot_id, newData);
      }
    }, 1000);
  }
}
```

## Summary

The new tile system provides:
1. **Better performance** through compression and caching
2. **Predictable updates** every 10 seconds
3. **Smooth visualization** with 1-second interpolation
4. **Scalability** for hundreds of concurrent viewers
5. **60-second delay** for synchronized viewing experience

The main work for frontend is:
1. Handle compressed delta updates instead of individual track updates
2. Implement smooth interpolation between 10-second updates
3. Track viewport and request visible tiles
4. Decompress gzipped data