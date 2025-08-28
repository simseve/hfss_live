# GPS TCP Server for TK905B and TK103 Trackers

## Overview
Production-ready TCP server for GPS trackers that supports both Watch protocol (TK905B) and TK103 protocol. Designed to handle real-world tracker behavior including frequent reconnections due to coverage issues.

## Features

### Protocol Support
- **Watch Protocol** (TK905B): Full support for location, heartbeat, alarm messages
- **TK103 Protocol**: Login, location, and heartbeat messages
- **Auto-detection**: Automatically identifies protocol based on message format

### Tracker-Friendly Design
Understanding that GPS trackers frequently lose and regain signal (tunnels, buildings, poor coverage), the server is configured to:

- **Allow frequent reconnections**: Up to 100 reconnections per 5-minute window
- **No penalty for coverage loss**: Reconnections due to signal loss are not penalized
- **Generous message rates**: 20 messages per minute allowed
- **Burst handling**: Minimum 2-second interval between messages (allows catch-up after reconnection)
- **Long idle timeout**: 5 minutes before considering connection dead

### Security Features
- **Attack detection**: Only blocks IPs showing malicious patterns (>10 connections/second)
- **Short blacklist duration**: Only 1 minute for detected attacks
- **Localhost whitelist**: Testing from localhost is never blocked
- **Smart rate limiting**: Per-device limits prevent single device flooding
- **Malformed packet handling**: Safely rejects invalid data without crashing

### Production Features
- **Auto-restart**: Recovers from errors automatically
- **Log rotation**: Prevents disk fill with 10MB rotating logs
- **Real-time monitoring**: Statistics logged every minute
- **Graceful shutdown**: Proper cleanup on SIGTERM/SIGINT
- **Connection management**: Handles up to 1000 simultaneous connections

## Configuration

### Connection Limits
```python
MAX_CONNECTIONS = 1000           # Total simultaneous connections
MAX_CONNECTIONS_PER_IP = 50      # Per-IP limit (multiple devices behind NAT)
CONNECTION_TIMEOUT = 300          # 5 minutes idle timeout
```

### Rate Limiting (Per Device)
```python
RATE_LIMIT_MESSAGES = 20         # Messages per minute
RATE_LIMIT_WINDOW = 60           # Rolling window
MIN_MESSAGE_INTERVAL = 2         # Seconds between messages
```

### Reconnection Handling
```python
MAX_RECONNECT_ATTEMPTS = 100     # Allows for poor coverage
RECONNECT_COOLDOWN = 300         # 5-minute window
```

## Running the Server

### Basic Server
```bash
python tcp_server/gps_tcp_server.py [port]
```

### Hardened Production Server
```bash
python tcp_server/gps_tcp_server_hardened.py [port]
```

### Testing
```bash
# Run test client
python tcp_server/test_gps_client.py

# Run stress tests
python tcp_server/stress_test.py all localhost 9091

# Continuous stress test (5 minutes)
python tcp_server/stress_test.py continuous localhost 9091 300
```

## Message Formats

### Watch Protocol (TK905B)
```
Location: [3G*DEVICEID*LENGTH*UD2,DDMMYY,HHMMSS,A,LAT,N/S,LON,E/W,SPEED,HEADING,ALT,SATS,BATTERY,...]
Login: [3G*DEVICEID*0008*LK,0,0,BATTERY]
Heartbeat: [3G*DEVICEID*0010*HEART,BATTERY]
```

### TK103 Protocol
```
Location: (DEVICEID,BR00,DDMMYY,A,LLLL.LLLL,N/S,LLLL.LLLL,E/W,SPEED,HHMMSS,HEADING)
Login: (DEVICEID,BP05,...)
Heartbeat: (DEVICEID,BP04)
```

## Integration with FastAPI

The TCP server can be integrated with your existing FastAPI application to run alongside HTTP endpoints. See `app.py` for integration examples.

## Logs

- **Server logs**: `logs/gps_tcp_server.log` (rotating, max 10MB)
- **GPS data log**: `gps_tcp_data.log` (JSON format for processing)

## Deployment

### Docker
```dockerfile
EXPOSE 9090/tcp
CMD ["python", "tcp_server/gps_tcp_server_hardened.py", "9090"]
```

### Systemd Service
```ini
[Service]
ExecStart=/usr/bin/python3 /path/to/tcp_server/gps_tcp_server_hardened.py 9090
Restart=always
```

## Monitoring

Server provides real-time statistics every minute:
- Active connections
- Messages received
- Valid locations
- Error count
- Uptime
- Blacklisted IPs (if any)

## Troubleshooting

### Device keeps reconnecting
- Normal behavior for trackers with poor signal
- Check device logs for GPS fix status
- Server handles this gracefully

### Connection rejected
- Check if IP is blacklisted (very rare, only for attacks)
- Verify not exceeding 50 connections from same IP
- Wait 1 minute if blacklisted

### No data received
- Verify device is sending to correct port
- Check protocol format matches Watch or TK103
- Enable debug logging to see raw packets