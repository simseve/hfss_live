# Datadog Metrics Mapping

## Dashboard Expects vs Pusher Sends

### Live Tracking
| Dashboard Expects | Pusher Currently Sends | Fixed |
|------------------|------------------------|-------|
| `hfss.live.messages_per_second` | `hfss.live.messages_per_second` | ✅ |
| `hfss.live.active_flights` | `hfss.live.active_flights` | ✅ |
| `hfss.live.active_devices` | `hfss.live.active_devices` | ✅ |
| `hfss.live.total_points` | `hfss.live.total_points` | ✅ |

### Queue Metrics
| Dashboard Expects | Pusher Currently Sends | Fixed |
|------------------|------------------------|-------|
| `hfss.queue.dlq_size` (sum all) | `hfss.queue.dlq_size` with tags | ✅ |
| `hfss.queue.pending` by queue_type | `hfss.queue.pending` with tags | ✅ |
| `hfss.queue.total_pending` | `hfss.queue.total_pending` | ✅ |
| `hfss.queue.total_dlq` | `hfss.queue.total_dlq` | ✅ |

### Database Metrics
| Dashboard Expects | Pusher Currently Sends | Fixed |
|------------------|------------------------|-------|
| `hfss.database.connections_active` | `hfss.database.connections_active` | ✅ |
| `hfss.database.connections_idle` | `hfss.database.connections_idle` | ✅ |
| `hfss.database.table_size` by table | `hfss.database.table_size` with tags | ✅ |

### GPS TCP Metrics
| Dashboard Expects | Pusher Currently Sends | Fixed |
|------------------|------------------------|-------|
| `hfss.gps_tcp.active_connections` | `hfss.gps_tcp.active_connections` | ✅ |

### API Metrics (from middleware)
| Dashboard Expects | Pusher Currently Sends | Fixed |
|------------------|------------------------|-------|
| `hfss.api.response_time` by endpoint | `hfss.api.response_time` with tags | ✅ |
| `hfss.api.requests` by endpoint | `hfss.api.requests` with tags | ✅ |

### Upload Metrics
| Dashboard Expects | Pusher Currently Sends | Fixed |
|------------------|------------------------|-------|
| `hfss.uploads.total` | `hfss.uploads.total` | ✅ |
| `hfss.uploads.last_hour` | `hfss.uploads.last_hour` | ✅ |

### Platform Health
| Dashboard Expects | Pusher Currently Sends | Fixed |
|------------------|------------------------|-------|
| `hfss.platform.health` | `hfss.platform.health` | ✅ |

All metrics match 100%!