# HFSS Live Platform Monitoring with Datadog

## Overview

The platform now has comprehensive monitoring integrated with Datadog for real-time metrics, alerting, and performance tracking across all components:

- **Live Tracking**: Active flights, devices, messages per second
- **Upload System**: File processing, queue status
- **Scoring Batch**: Batch processing metrics
- **GPS TCP Server**: Connections, device tracking, message rates
- **Queue System**: Pending items, DLQ monitoring, throughput
- **Database**: Connection pools, query performance, table sizes

## Quick Start

### 1. Install Dependencies

```bash
pip install datadog prometheus-client
```

### 2. Configure Environment Variables

```bash
# Datadog Configuration
export DD_API_KEY="your-datadog-api-key"
export DD_APP_KEY="your-datadog-app-key"
export DD_AGENT_HOST="localhost"  # Or your Datadog agent host
export DD_DOGSTATSD_PORT="8125"
export DD_ENV="production"
export DD_VERSION="1.0.0"

# Alert Thresholds (optional, defaults shown)
export ALERT_QUEUE_PENDING_WARN="1000"
export ALERT_QUEUE_PENDING_CRIT="5000"
export ALERT_DLQ_WARN="10"
export ALERT_DLQ_CRIT="100"
export ALERT_PROCESSING_LAG="300"
export ALERT_NO_DATA_MINUTES="5"
export ALERT_ERROR_RATE="5.0"
export ALERT_LATENCY_WARN="1000"
export ALERT_LATENCY_CRIT="5000"
```

### 3. Run with Datadog Agent

```bash
# Docker Compose with Datadog
docker-compose -f docker-compose.yml -f docker-compose.datadog.yml up -d

# Or run Datadog Agent separately
docker run -d \
  --name datadog-agent \
  -e DD_API_KEY=$DD_API_KEY \
  -e DD_SITE="datadoghq.com" \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /proc/:/host/proc/:ro \
  -v /sys/fs/cgroup/:/host/sys/fs/cgroup:ro \
  -p 8125:8125/udp \
  datadog/agent:latest
```

## API Endpoints

### Main Monitoring Dashboard
```bash
GET /api/monitoring/dashboard
```

Returns comprehensive platform metrics:
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "platform_health": {
    "status": "healthy",
    "issues": [],
    "components_checked": 6
  },
  "live_tracking": {
    "active_flights": 42,
    "active_devices": 38,
    "messages_per_second": 125.5,
    "queue_pending": 250,
    "dlq_size": 0
  },
  "uploads": {
    "total_uploads": 1543,
    "uploads_last_hour": 23,
    "queue_pending": 5,
    "dlq_size": 0
  },
  "scoring": {
    "queue_pending": 12,
    "batches_processed": 456,
    "dlq_size": 0
  },
  "gps_tcp_server": {
    "status": "enabled",
    "active_connections": 38,
    "messages_total": 1234567,
    "devices_total": 142
  },
  "database": {
    "connections_active": 15,
    "connections_idle": 5,
    "table_sizes": {
      "live_track_points": 2450000,
      "uploaded_track_points": 8900000,
      "flights": 3456,
      "races": 89
    }
  },
  "queues": {
    "status": "healthy",
    "queues": {
      "live_points": {
        "pending": 250,
        "processing": 100,
        "dlq_size": 0,
        "status": "healthy"
      },
      "upload_points": {
        "pending": 5,
        "processing": 0,
        "dlq_size": 0,
        "status": "healthy"
      },
      "scoring_batch": {
        "pending": 12,
        "processing": 1,
        "dlq_size": 0,
        "status": "healthy"
      }
    },
    "summary": {
      "total_pending": 267,
      "total_dlq": 0
    }
  }
}
```

### Queue Health Check
```bash
GET /admin/queue/health
```

### Queue Statistics
```bash
GET /admin/queue/stats
```

### Device Metrics
```bash
GET /api/monitoring/metrics/devices?active_only=true
```

### Live Tracking Metrics
```bash
GET /api/monitoring/metrics/live?window_minutes=5
```

### Queue Metrics with DLQ Status
```bash
GET /api/monitoring/metrics/queues
```

### Process Dead Letter Queue
```bash
POST /admin/queue/process-dlq/{queue_type}?dry_run=false
```

### Force Process Queue Items
```bash
POST /admin/queue/force-process/{queue_type}?batch_size=100
```

### Test Alert System
```bash
POST /api/monitoring/alert/test?alert_type=warning&message=Test%20alert
```

## Datadog Metrics

### Live Tracking Metrics
- `hfss.live.active_flights` - Number of active flights
- `hfss.live.active_devices` - Number of active devices
- `hfss.live.messages_per_second` - Message throughput rate
- `hfss.live.points_received` - Total points received
- `hfss.live.points_processed` - Successfully processed points
- `hfss.live.points_failed` - Failed points (in DLQ)
- `hfss.live.latency` - Processing latency histogram

### Upload Metrics
- `hfss.upload.files_uploaded` - Files uploaded counter
- `hfss.upload.files_processing` - Files currently processing
- `hfss.upload.files_completed` - Completed uploads
- `hfss.upload.files_failed` - Failed uploads
- `hfss.upload.file_size_mb` - File size distribution
- `hfss.upload.processing_time` - Processing time histogram

### Scoring Metrics
- `hfss.scoring.batches_processed` - Batches processed counter
- `hfss.scoring.batch_size` - Average batch size
- `hfss.scoring.batch_processing_time` - Processing time histogram
- `hfss.scoring.flights_scored` - Flights scored counter
- `hfss.scoring.scoring_errors` - Scoring errors counter
- `hfss.scoring.points_per_second` - Processing throughput

### GPS TCP Server Metrics
- `hfss.gps_tcp.active_connections` - Active TCP connections
- `hfss.gps_tcp.connections_total` - Total connections counter
- `hfss.gps_tcp.connections_failed` - Failed connections
- `hfss.gps_tcp.active_devices` - Active GPS devices
- `hfss.gps_tcp.blacklisted_ips` - Blacklisted IP count
- `hfss.gps_tcp.messages_received` - Messages received counter
- `hfss.gps_tcp.messages_per_second` - Message rate
- `hfss.gps_tcp.messages_invalid` - Invalid messages counter
- `hfss.gps_tcp.locations_valid` - Valid GPS locations counter

### Queue Metrics
- `hfss.queue.pending` - Items pending in queue (tagged by queue_type)
- `hfss.queue.processing` - Items currently processing
- `hfss.queue.dlq_size` - Dead letter queue size
- `hfss.queue.throughput` - Processing throughput
- `hfss.queue.dlq_items` - Items added to DLQ

### Database Metrics
- `hfss.database.connections_active` - Active DB connections
- `hfss.database.connections_idle` - Idle connections
- `hfss.database.connections_waiting` - Waiting connections
- `hfss.database.query_latency` - Query latency histogram
- `hfss.database.table_size` - Table sizes (tagged by table)
- `hfss.database.replication_lag` - Replication lag in seconds

### API Metrics
- `hfss.api.requests` - Request counter (tagged by endpoint, method, status)
- `hfss.api.response_time` - Response time histogram
- `hfss.api.errors` - Error counter

### Service Checks
- `hfss.platform.health` - Overall platform health (0=OK, 1=WARNING, 2=CRITICAL)
- `hfss.live_tracking.health` - Live tracking component health
- `hfss.uploads.health` - Upload system health
- `hfss.scoring.health` - Scoring system health
- `hfss.gps_tcp.health` - GPS TCP server health
- `hfss.database.health` - Database health
- `hfss.queues.health` - Queue system health

## Alerting Rules

### Queue Alerts
- **Warning**: Queue pending > 1000 items
- **Critical**: Queue pending > 5000 items
- **Warning**: DLQ > 10 items
- **Critical**: DLQ > 100 items

### Live Tracking Alerts
- **Warning**: No data for 5 minutes
- **Warning**: Error rate > 5%
- **Warning**: Latency > 1000ms
- **Critical**: Latency > 5000ms

### GPS TCP Server Alerts
- **Warning**: Blacklisted IPs > 5
- **Critical**: Blacklisted IPs > 20
- **Warning**: Invalid message rate > 10%

### Database Alerts
- **Warning**: Connection pool > 80%
- **Critical**: Connection pool > 95%
- **Warning**: Replication lag > 10 seconds

### API Alerts
- **Error**: 5xx responses trigger immediate alerts
- **Warning**: Error rate > 1%

## Datadog Dashboard Setup

Create a custom dashboard in Datadog with these widgets:

### 1. Platform Overview
- Service Map widget showing all components
- Health status indicators for each component
- Alert summary widget

### 2. Live Tracking Panel
- Line graph: Messages per second over time
- Gauge: Active flights and devices
- Heatmap: Processing latency distribution
- Counter: Total points processed today

### 3. Queue Health Panel
- Stacked bar: Queue sizes by type
- Line graph: DLQ trends over time
- Table: Queue statistics with status indicators

### 4. GPS TCP Server Panel
- Line graph: Active connections over time
- Counter: Total devices connected
- List: Blacklisted IPs (if any)
- Pie chart: Valid vs invalid messages

### 5. Database Performance
- Line graph: Connection pool usage
- Histogram: Query latency distribution
- Counter: Table sizes and growth rate

### 6. API Performance
- Line graph: Request rate by endpoint
- Histogram: Response time distribution
- Error rate percentage
- Top 10 slowest endpoints

## Troubleshooting

### No Metrics in Datadog
1. Check DD_API_KEY is set correctly
2. Verify Datadog Agent is running: `docker ps | grep datadog`
3. Check logs: `docker logs datadog-agent`
4. Test connectivity: `echo "test.metric:1|c" | nc -u -w1 localhost 8125`

### High DLQ Count
1. Check queue health: `GET /admin/queue/health`
2. Inspect DLQ items: `POST /admin/queue/process-dlq/{queue_type}?dry_run=true`
3. Process DLQ: `POST /admin/queue/process-dlq/{queue_type}?dry_run=false`
4. Check error logs for processing failures

### Missing GPS TCP Metrics
1. Verify GPS_TCP_ENABLED=true in config
2. Check GPS TCP server is running
3. Verify port connectivity: `telnet gps-tcp-server 5000`

### Database Connection Issues
1. Check connection pool: `GET /api/monitoring/dashboard`
2. Look for connection leaks in logs
3. Verify database is accessible
4. Check for long-running queries

## Monitoring Best Practices

1. **Set Up Alerts**: Configure Datadog monitors for critical metrics
2. **Regular Health Checks**: Use `/api/monitoring/dashboard` for quick status
3. **Monitor DLQ**: Check dead letter queues daily
4. **Track Trends**: Watch for gradual degradation in performance
5. **Capacity Planning**: Monitor growth in table sizes and message rates
6. **Test Alerts**: Regularly test alert system with test endpoint
7. **Document Incidents**: Track patterns in issues for root cause analysis

## Performance Optimization Tips

1. **Queue Tuning**: Adjust batch sizes based on throughput needs
2. **Connection Pooling**: Optimize database connection pool size
3. **Caching**: Use Redis caching for frequently accessed data
4. **Compression**: Enable TimescaleDB compression for historical data
5. **Indexing**: Ensure proper indexes on frequently queried columns
6. **Retention**: Set appropriate data retention policies

## Integration with Other Tools

### Prometheus Export
The monitoring system also exports Prometheus metrics on port 9090:
```bash
curl http://localhost:9090/metrics
```

### Grafana Integration
Import the provided Grafana dashboard JSON for visualization:
```bash
grafana/dashboard-hfss-platform.json
```

### PagerDuty Integration
Configure Datadog to send critical alerts to PagerDuty for on-call rotation.

### Slack Integration
Set up Datadog Slack integration for team notifications on warnings and errors.