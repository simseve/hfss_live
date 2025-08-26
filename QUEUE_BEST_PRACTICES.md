# Queue Management Best Practices

## Overview
This document outlines best practices for managing Redis queues to prevent data loss and handle stuck items effectively.

## Architecture

### Queue Structure
- **Priority Queue** (`queue:{name}`): Primary storage using sorted sets
- **Dead Letter Queue** (`dlq:{name}`): Failed items that couldn't be processed
- **List Queue** (`list:{name}`): Legacy support (being phased out)

### Processing Flow
```
New Data → Priority Queue → Processing → Success → Database
                    ↓ (on failure)
                Retry (3x with exponential backoff)
                    ↓ (max retries exceeded)
                Dead Letter Queue → Manual Review
```

## Best Practices

### 1. Prevent Queue Buildup

#### Foreign Key Validation
- **Always validate foreign keys before processing**
- Points referencing non-existent flights go directly to DLQ
- Prevents repeated processing failures

```python
# Example: Validate before processing
valid_points, invalid_points = await validate_foreign_keys(points)
if invalid_points:
    await move_to_dlq(invalid_points, "Invalid foreign key")
```

#### Batch Processing
- Process in reasonable batch sizes (default: 500 items)
- Prevents memory issues and timeout errors
- Allows better error isolation

### 2. Error Handling

#### Retry Logic
- **Exponential backoff**: 1s, 2s, 4s, 8s... (max 60s)
- **Max retries**: 3 attempts before DLQ
- **Selective retry**: Only retry transient errors

#### Dead Letter Queue (DLQ)
- Stores permanently failed items with metadata
- Includes failure reason and timestamp
- Allows manual review and reprocessing

### 3. Monitoring

#### Health Checks
```bash
# Check queue health via API
curl http://localhost:8000/admin/queue/health

# Check specific queue stats
curl http://localhost:8000/admin/queue/stats
```

#### Alert Thresholds
- **Warning**: > 1,000 pending items
- **Critical**: > 5,000 pending items
- **DLQ Warning**: > 10 items
- **DLQ Critical**: > 100 items

### 4. Recovery Procedures

#### Immediate Actions for Stuck Queues

1. **Check Queue Status**
```bash
python process_stuck_queue.py --status
```

2. **Force Process Items**
```bash
# Process specific queue
curl -X POST http://localhost:8000/admin/queue/force-process/live_points?batch_size=100
```

3. **Process DLQ Items**
```bash
# Dry run first
curl -X POST http://localhost:8000/admin/queue/process-dlq/live_points?dry_run=true

# Then process
curl -X POST http://localhost:8000/admin/queue/process-dlq/live_points?dry_run=false
```

4. **Clear Orphaned Items** (last resort)
```bash
# Clear queue with invalid data
curl -X DELETE "http://localhost:8000/admin/queue/clear/live_points?include_dlq=true&confirm=true"
```

### 5. Automated Management

#### Monitoring Script
```bash
# Run monitoring once
python queue_monitor.py --once

# Continuous monitoring (as service)
python queue_monitor.py
```

#### Cron Jobs
```cron
# Check queue health every 5 minutes
*/5 * * * * /usr/bin/python3 /path/to/queue_monitor.py --once

# Clean up old items daily at 2 AM
0 2 * * * curl -X POST http://localhost:8000/admin/queue/cleanup?max_age_hours=24
```

### 6. Prevention Strategies

#### Application Level
1. **Validate data before queuing**
2. **Use ON CONFLICT DO NOTHING for duplicates**
3. **Implement circuit breakers for failing services**
4. **Set appropriate timeouts**

#### Database Level
1. **Use deferred foreign key constraints where appropriate**
2. **Implement cascade deletes carefully**
3. **Regular database maintenance**

#### Infrastructure Level
1. **Monitor Redis memory usage**
2. **Set up Redis persistence (AOF/RDB)**
3. **Regular backups of critical data**
4. **Use Redis Sentinel for high availability**

## API Endpoints

### Queue Management

| Endpoint | Method | Description |
|----------|---------|-------------|
| `/admin/queue/health` | GET | Get queue health status |
| `/admin/queue/stats` | GET | Get detailed statistics |
| `/admin/queue/process-dlq/{queue}` | POST | Process DLQ items |
| `/admin/queue/clear/{queue}` | DELETE | Clear queue (with confirmation) |
| `/admin/queue/cleanup` | POST | Clean old items |
| `/admin/queue/force-process/{queue}` | POST | Force process items |

## Troubleshooting

### Common Issues

1. **Foreign Key Violations**
   - **Cause**: Flight deleted while points in queue
   - **Solution**: Items automatically moved to DLQ
   - **Prevention**: Process queues before deleting flights

2. **Queue Growth**
   - **Cause**: Processing slower than ingestion
   - **Solution**: Scale processing workers or batch size
   - **Prevention**: Monitor queue size trends

3. **SSL Connection Errors**
   - **Cause**: Database connection timeout
   - **Solution**: Already handled by retry logic
   - **Prevention**: Connection pooling configured

4. **Memory Issues**
   - **Cause**: Too many items in memory
   - **Solution**: Reduce batch size
   - **Prevention**: Set Redis memory limits

## Maintenance Schedule

- **Every 5 minutes**: Health check and alerting
- **Hourly**: Process small DLQs automatically
- **Daily**: Clean items > 24 hours old
- **Weekly**: Review DLQ items and patterns
- **Monthly**: Analyze failure trends and optimize

## Emergency Contacts

Configure in `queue_monitor.py`:
- Webhook URL for alerts
- Email addresses for critical issues
- PagerDuty integration for 24/7 monitoring

## Performance Tuning

### Redis Configuration
```conf
# redis.conf
maxmemory 2gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
```

### Application Configuration
```python
# Enhanced processor settings
MAX_RETRIES = 3
BATCH_SIZE = 500
DLQ_THRESHOLD = 3
MAX_RETRY_DELAY = 60
```

## Metrics to Track

1. **Queue Size** - Current items pending
2. **Processing Rate** - Items/second processed
3. **Error Rate** - Failed items/total items
4. **DLQ Growth** - Items added to DLQ/hour
5. **Processing Latency** - Time from queue to database
6. **Recovery Rate** - DLQ items successfully reprocessed

## Conclusion

Following these best practices ensures:
- ✅ No data loss
- ✅ Quick recovery from failures
- ✅ Visibility into queue health
- ✅ Automated handling of common issues
- ✅ Manual controls for edge cases

The system is designed to be self-healing with manual overrides when needed.