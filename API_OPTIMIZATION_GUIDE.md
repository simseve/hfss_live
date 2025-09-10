# API Performance Optimization Guide

## Overview
New optimized endpoints to fix slow page loads and timeouts in HFSS tracker.

## Problem
- `/tracking/live/users` takes **29+ seconds** (loads all pilots/flights)
- `/tracking/admin/delete-pilot-flights/{id}` blocks until deletion completes
- Multiple simultaneous requests causing database connection exhaustion

## New Optimized Endpoints

### 1. Fast Summary Endpoint
**GET** `/tracking/live/summary`

**Response Time:** <1 second (vs 29 seconds)

**Returns:**
```json
{
  "summary": {
    "total_flights": 245,
    "total_pilots": 35
  },
  "pilots": [
    {
      "pilot_id": "123",
      "pilot_name": "John Doe",
      "flight_count": 5,
      "last_activity": "2025-09-09T15:30:00Z"
    }
  ]
}
```

**Use for:** Initial page load, pilot list display

---

### 2. Per-Pilot Flights Endpoint  
**GET** `/tracking/live/pilot/{pilot_id}/flights`

**Response Time:** <500ms per pilot

**Returns:**
```json
{
  "pilot_id": "123",
  "flights": [
    {
      "uuid": "abc-def",
      "source": "live",
      "first_fix": {...},
      "last_fix": {...},
      "duration_seconds": 3600
    }
  ]
}
```

**Use for:** Load when user expands pilot accordion

---

### 3. Async Delete Endpoints

#### Delete All Pilot Flights
**DELETE** `/tracking/admin/delete-pilot-flights-async/{pilot_id}`

**Response Time:** Immediate (202 Accepted)

**Returns:**
```json
{
  "status_code": 202,
  "deletion_id": "xyz-789",
  "message": "Processing in background",
  "status_url": "/tracking/deletion-status/xyz-789"
}
```

#### Delete Single Flight (NEW)
**DELETE** `/tracking/tracks/fuuid-async/{flight_uuid}?source=live`

**Response Time:** Immediate (202 Accepted)

**Returns:**
```json
{
  "status_code": 202,
  "deletion_id": "abc-123",
  "message": "Flight deletion accepted (contains 5000 points)",
  "status_url": "/tracking/deletion-status/abc-123"
}
```

**Then check status for both:**
**GET** `/tracking/deletion-status/{deletion_id}`

```json
{
  "status": "completed",
  "deleted_flights": 1,
  "deleted_points": 5000,
  "pilot_name": "John Doe",
  "flight_uuid": "abc-def-ghi"
}
```

**Use for:** Delete operations without blocking UI (especially for flights with thousands of points)

---

## Migration Guide for HFSS

### Option 1: Minimal Changes (Recommended)
1. Replace `/tracking/live/users` with `/tracking/live/summary` for initial load
2. Keep delete as-is (still works, just slow)

### Option 2: Full Optimization
1. Use summary endpoint for page load
2. Lazy-load flights when pilot expands
3. Use async delete with status polling

### Option 3: No Changes
- Everything still works with existing endpoints
- Just remains slow (29+ seconds)

## Performance Gains
| Operation | Old Time | New Time | Improvement |
|-----------|----------|----------|-------------|
| Page Load | 29s | <1s | **30x faster** |
| Delete Pilot | 30s blocking | Instant (202) | **Non-blocking** |
| Load Pilot | N/A (all loaded) | <500ms | **On-demand** |

## Authentication
All endpoints require same JWT bearer token as before.

## Backwards Compatibility
✅ All original endpoints remain unchanged
✅ No breaking changes
✅ Can migrate incrementally