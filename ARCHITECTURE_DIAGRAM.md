# Redis Queue System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CLIENT REQUESTS                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          FASTAPI ENDPOINTS                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐      │
│  │/live        │ │/upload      │ │/flymaster   │ │/scoring     │      │
│  │Priority: 1  │ │Priority: 2  │ │Priority: 3  │ │Priority: 2  │      │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                         ┌─────────▼─────────┐
                         │  REDIS AVAILABLE? │
                         └─────────┬─────────┘
                              YES  │  NO
                    ┌──────────────┘  └──────────────┐
                    ▼                                ▼
┌─────────────────────────────────────┐    ┌─────────────────────┐
│           REDIS QUEUES              │    │   FALLBACK MODE     │
│  ┌─────────────────────────────────┐│    │                     │
│  │ live_points    │ Priority: 1    ││    │  Direct DB Insert   │
│  │ upload_points  │ Priority: 2    ││    │  (Synchronous)      │
│  │ flymaster_pts  │ Priority: 3    ││    │                     │
│  │ scoring_points │ Priority: 2    ││    │  Response: 201      │
│  └─────────────────────────────────┘│    └─────────────────────┘
│              │                      │
│              ▼                      │         ▲
│    ┌─────────────────────────────┐  │         │
│    │   BACKGROUND PROCESSORS     │  │         │
│    │  ┌─────────────────────────┐│  │         │
│    │  │ Processor 1: live_pts   ││  │         │
│    │  │ Processor 2: upload_pts ││  │         │
│    │  │ Processor 3: flymaster  ││  │         │
│    │  │ Processor 4: scoring    ││  │         │
│    │  └─────────────────────────┘│  │         │
│    └─────────────────────────────┘  │         │
└─────────────────────────────────────┘         │
                    │                           │
              Batch │ Processing                │ Failure
            (500-1000│points)                   │ Scenarios
                    │                           │
                    ▼                           │
┌─────────────────────────────────────────────┐ │
│              TIMESCALEDB                    │ │
│  ┌─────────────────────────────────────────┐│ │
│  │ live_track_points    (Hypertable)      ││ │
│  │ uploaded_track_points (Hypertable)     ││ │
│  │ flymaster           (Hypertable)       ││ │
│  │ scoring_tracks      (Hypertable)       ││ │
│  └─────────────────────────────────────────┘│ │
│                                             │ │
│  ON CONFLICT DO NOTHING (Deduplication)    │ │
└─────────────────────────────────────────────┘ │
                    │                           │
                    ▼                           │
┌─────────────────────────────────────────────┐ │
│              SUCCESS RESPONSE               │ │
│                                             │ │
│  Queue Mode: 202 Accepted (Immediate)      │ │
│  Fallback:   201 Created (After Insert)    │◄┘
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                        MONITORING ENDPOINTS                             │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ GET /health                                                         ││
│  │ • Database connection status                                        ││
│  │ • Redis connection status                                           ││
│  │ • Basic queue statistics                                            ││
│  │                                                                     ││
│  │ GET /queue/status                                                   ││
│  │ • Detailed queue statistics (pending, processed, failed)           ││
│  │ • Background processor status                                       ││
│  │ • Processing performance metrics                                    ││
│  └─────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

## Key Features

### 🚀 Performance

- **Immediate Response**: 202 Accepted in ~5-10ms
- **Background Processing**: 500-1000 points per batch
- **Concurrent Workers**: 4 background processors
- **High Throughput**: Non-blocking async processing

### 🛡️ Reliability

- **Fallback Mode**: Direct DB insert if Redis unavailable
- **Conflict Resolution**: PostgreSQL ON CONFLICT DO NOTHING
- **Error Handling**: Comprehensive error logging and recovery
- **Graceful Shutdown**: Proper cleanup of connections and tasks

### 📊 Monitoring

- **Health Checks**: Real-time system status
- **Queue Statistics**: Pending, processed, failed counts
- **Performance Metrics**: Processing rates and latencies
- **Redis Monitoring**: Connection status and memory usage

### ⚙️ Configuration

- **Environment Aware**: Dev (localhost) vs Prod (redis service)
- **Flexible Redis**: URL or individual settings
- **Configurable Batching**: Adjustable batch sizes
- **Priority Queues**: Different priorities for different endpoints
