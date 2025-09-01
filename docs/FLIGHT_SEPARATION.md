# Flight Separation Logic Documentation

## Overview
This document describes how flights are separated for different tracking devices in the HFSS system.

## Device Types and Flight Management

### 1. Mobile Apps (iOS/Android)
**Flight Separation**: ❌ NOT USED - Apps manage their own flight IDs
- **Endpoints**: `/api/v2/live`, `/api/v2/upload`
- **Flight ID Format**: Provided by the app (e.g., `"app-{uuid}"`)
- **Start/Stop**: Manual control via app UI
- **Source**: `'live'` or `'upload'`

Mobile apps have explicit start/stop buttons and manage their own flight lifecycle. The server accepts whatever flight_id the app provides.

### 2. TK905B GPS Trackers
**Flight Separation**: ✅ AUTOMATIC
- **Protocol**: JT808 TCP protocol
- **Flight ID Format**: `tk905b-{pilot_id}-{race_id}-{device_id}-{suffix}`
- **Source**: `'tk905b_live'`
- **Separation Rules**:
  - New day at midnight (race timezone) → suffix: `YYYYMMDD`
  - 3+ hours of inactivity → suffix: `HHMM`
  - Landing detected (10+ min on ground) → suffix: `LHHMM`

### 3. Flymaster GPS Trackers
**Flight Separation**: ✅ AUTOMATIC
- **Protocol**: Custom Flymaster protocol
- **Flight ID Format**: `flymaster-{pilot_id}-{race_id}-{device_id}-{suffix}`
- **Source**: `'flymaster_live'`
- **Separation Rules**:
  - New day at midnight (race timezone) → suffix: `YYYYMMDD`
  - 3+ hours of inactivity → suffix: `HHMM`
  - Landing detected (10+ min on ground) → suffix: `LHHMM`

## Implementation Details

### Flight Separator Utility
**Location**: `/utils/flight_separator.py`

```python
FlightSeparator.should_create_new_flight(
    device_id: str,
    current_point: Dict,
    last_flight: Optional[Dict],
    race_timezone: str
) -> tuple[bool, str]
```

### Configuration
- **Inactivity Threshold**: 3 hours (configurable)
- **Landing Duration**: 10 minutes on ground
- **Speed Threshold**: < 5 km/h considered stopped
- **Altitude Variation**: < 10m for landing detection

### Integration Points

#### TK905B Integration
**File**: `tcp_server/jt808_processor.py`
- Checks for new flight on each location report
- Caches flight info for 1 hour to reduce DB queries
- Creates new flight based on separation rules

#### Flymaster Integration
**File**: `redis_queue_system/point_processor.py`
- Checks for new flight when processing point batches
- Applied in `_get_or_create_flymaster_flight()` method
- Uses same separation logic as TK905B

#### Mobile App Integration
**Files**: `api/routes.py` (endpoints `/live` and `/upload`)
- **NO SEPARATION LOGIC APPLIED**
- Directly uses `data.flight_id` from request
- Apps control their own flight lifecycle

## Database Schema

### Flight Table
```sql
flight_id: VARCHAR  -- Unique identifier with optional suffix
source: VARCHAR     -- 'live', 'upload', 'tk905b_live', 'flymaster_live'
device_id: VARCHAR  -- Device identifier
created_at: TIMESTAMP
first_fix: JSONB    -- Updated by triggers
last_fix: JSONB     -- Updated by triggers
total_points: INT   -- Updated by triggers
flight_state: JSONB -- Landing detection info
```

### Triggers
Database triggers automatically update `first_fix`, `last_fix`, and `total_points` based on the `flight_id` field when track points are inserted.

## Examples

### TK905B Flight IDs
```
Morning flight:  tk905b-pilot123-race456-9590046863-20250901
Afternoon flight: tk905b-pilot123-race456-9590046863-1430
After landing:    tk905b-pilot123-race456-9590046863-L1630
```

### Flymaster Flight IDs
```
First flight:     flymaster-pilot789-race456-FM12345-20250901
After 4hr break:  flymaster-pilot789-race456-FM12345-1400
After landing:    flymaster-pilot789-race456-FM12345-L1545
```

### Mobile App Flight IDs (unchanged)
```
iOS app:     ios-550e8400-e29b-41d4-a716-446655440000
Android app: android-6ba7b810-9dad-11d1-80b4-00c04fd430c8
```

## Benefits

1. **Automatic Flight Management**: No manual intervention needed for continuous trackers
2. **Backward Compatible**: Mobile apps continue to work unchanged
3. **Flexible Rules**: Easy to adjust thresholds for different use cases
4. **Clear Separation**: Each flying session is properly separated
5. **Timezone Aware**: Respects race timezone for day boundaries

## Testing

Run the test suite:
```bash
python test_flight_separation.py
```

This tests:
- No previous flight scenario
- New day detection
- Inactivity periods
- Short gaps (continue same flight)
- Landing detection
- Flight ID suffix generation