# Redis Queue System Documentation

## Overview

The Redis-based queue system has been implemented to handle high-volume GPS point insertions efficiently. This system improves performance by:

1. **Asynchronous Processing**: Points are queued immediately and processed in the background
2. **Batch Processing**: Points are processed in configurable batches (500-1000 points)
3. **Priority Handling**: Different endpoint types have different priorities
4. **Fallback Mechanism**: Direct database insertion if Redis is unavailable
5. **Conflict Resolution**: Uses PostgreSQL's `ON CONFLICT DO NOTHING` for duplicate handling

## Architecture

### Components

1. **RedisPointQueue** (`queue/redis_queue.py`)

   - Manages Redis connections and queue operations
   - Handles point queueing with priority support
   - Provides batch dequeuing functionality

2. **PointProcessor** (`queue/point_processor.py`)

   - Background worker processes for each queue type
   - Batch processing with error handling
   - Processing statistics and monitoring

3. **Queue Integration** (in route files)
   - Modified endpoints to use queueing with fallback
   - Priority assignment based on use case

### Queue Types

| Queue Type         | Priority   | Use Case             | Table                   |
| ------------------ | ---------- | -------------------- | ----------------------- |
| `live_points`      | 1 (High)   | Real-time tracking   | `live_track_points`     |
| `upload_points`    | 2 (Medium) | Track uploads        | `uploaded_track_points` |
| `flymaster_points` | 3 (Lower)  | Bulk device uploads  | `flymaster`             |
| `scoring_points`   | 2 (Medium) | Scoring calculations | `scoring_tracks`        |

## Configuration

### Redis Settings

Add to your `.env` file:

```env
# Redis Configuration
REDIS_URL=redis://localhost:6379/0  # Optional: Full Redis URL
REDIS_HOST=localhost                # Default: localhost
REDIS_PORT=6379                     # Default: 6379
REDIS_DB=0                          # Default: 0
REDIS_PASSWORD=                     # Optional: Redis password
REDIS_MAX_CONNECTIONS=20            # Default: 20
```

### Docker Compose

Add Redis service to your `docker-compose.yml`:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - '6379:6379'
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

volumes:
  redis_data:
```

## API Endpoints

### Health Check

- **GET** `/health` - Includes Redis connection status and queue statistics

### Queue Monitoring

- **GET** `/queue/status` - Detailed queue statistics and processor status

## Monitoring

### Queue Statistics

The system provides comprehensive monitoring:

```json
{
  "redis_connected": true,
  "queue_stats": {
    "live": {
      "queue_size": 0,
      "priority_queue_size": 0,
      "total_pending": 0
    },
    "upload": { ... },
    "flymaster": { ... },
    "scoring": { ... }
  },
  "processor_stats": {
    "processed": 1250,
    "failed": 2,
    "last_processed": "2025-06-08T10:30:00Z"
  }
}
```

### Logging

The system logs key operations:

- Queue connection status
- Points queued/processed
- Processing errors
- Performance metrics

## Performance Benefits

### Before (Direct DB Insert)

- Synchronous database operations
- High latency on large batches
- Potential timeout issues
- Single-threaded processing

### After (Redis Queue)

- Immediate response (202 Accepted)
- Background batch processing
- Configurable batch sizes
- Multiple concurrent processors
- Graceful degradation with fallback

## Fallback Mechanism

If Redis is unavailable:

1. Endpoints automatically fall back to direct database insertion
2. Users receive appropriate response indicating fallback mode
3. No data loss occurs
4. System remains functional

## Testing

Run the test script to verify functionality:

```bash
python test_redis_queue.py
```

This tests:

- Redis connectivity
- Point queueing
- Batch dequeuing
- Statistics collection

## Deployment Notes

1. **Redis Persistence**: Configure Redis with AOF (Append Only File) for data persistence
2. **Memory Management**: Monitor Redis memory usage with large queues
3. **Scaling**: Multiple application instances can share the same Redis queue
4. **Monitoring**: Set up alerts for queue depth and processing failures

## Error Handling

The system includes comprehensive error handling:

- Redis connection failures
- Queue processing errors
- Database insertion errors
- Graceful shutdown procedures

## Future Enhancements

Potential improvements:

1. **Dead Letter Queues**: For failed processing attempts
2. **Queue Sharding**: For extremely high volumes
3. **Metrics Export**: Prometheus/Grafana integration
4. **Auto-scaling**: Based on queue depth
5. **Compression**: For large point batches
