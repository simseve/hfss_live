"""
GPS TCP Server Monitoring Integration
Supports Datadog, Prometheus, and logging metrics
"""
import time
import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime
import os

logger = logging.getLogger(__name__)

class MetricsCollector:
    """Collect and report GPS TCP server metrics"""
    
    def __init__(self, server_instance):
        self.server = server_instance
        self.datadog_enabled = False
        self.datadog_client = None
        
        # Try to initialize Datadog if available
        try:
            import datadog
            datadog.initialize(
                api_key=os.getenv('DD_API_KEY'),
                app_key=os.getenv('DD_APP_KEY')
            )
            self.datadog_client = datadog
            self.datadog_enabled = bool(os.getenv('DD_API_KEY'))
            if self.datadog_enabled:
                logger.info("Datadog monitoring enabled")
        except ImportError:
            logger.info("Datadog not installed, metrics will be logged only")
        
        # Prometheus metrics setup
        self.prometheus_enabled = False
        try:
            from prometheus_client import Counter, Gauge, Histogram
            self.prom_connections = Gauge('gps_tcp_active_connections', 'Active GPS TCP connections')
            self.prom_messages = Counter('gps_tcp_messages_total', 'Total messages received')
            self.prom_valid_locations = Counter('gps_tcp_valid_locations_total', 'Total valid GPS locations')
            self.prom_errors = Counter('gps_tcp_errors_total', 'Total processing errors', ['error_type'])
            self.prom_message_latency = Histogram('gps_tcp_message_latency_seconds', 'Message processing latency')
            self.prometheus_enabled = True
            logger.info("Prometheus monitoring enabled")
        except ImportError:
            logger.info("Prometheus client not installed")
    
    def report_metrics(self):
        """Report current metrics to all configured backends"""
        try:
            stats = self.server.get_status()
            
            # Add calculated metrics
            uptime_seconds = self._parse_uptime(stats.get('uptime', '0:00:00'))
            message_rate = stats['total_messages'] / max(uptime_seconds, 1)
            
            metrics = {
                'gps.tcp.connections.active': stats['active_connections'],
                'gps.tcp.messages.total': stats['total_messages'],
                'gps.tcp.messages.rate': message_rate,
                'gps.tcp.locations.valid': stats['valid_locations'],
                'gps.tcp.ips.blacklisted': len(stats['blacklisted_ips']),
                'gps.tcp.uptime': uptime_seconds,
            }
            
            # Report to Datadog
            if self.datadog_enabled and self.datadog_client:
                for metric_name, value in metrics.items():
                    self.datadog_client.api.Metric.send(
                        metric=metric_name,
                        points=value,
                        tags=[
                            f"server:{os.getenv('HOSTNAME', 'unknown')}",
                            "service:gps_tcp_server"
                        ]
                    )
                
                # Send events for important changes
                if len(stats['blacklisted_ips']) > 0:
                    self.datadog_client.api.Event.create(
                        title="GPS TCP Server: IPs Blacklisted",
                        text=f"Blacklisted IPs: {', '.join(stats['blacklisted_ips'])}",
                        tags=["gps_tcp_server", "security"]
                    )
            
            # Update Prometheus metrics
            if self.prometheus_enabled:
                self.prom_connections.set(stats['active_connections'])
                self.prom_messages.inc(stats['total_messages'] - getattr(self, '_last_messages', 0))
                self.prom_valid_locations.inc(stats['valid_locations'] - getattr(self, '_last_locations', 0))
                self._last_messages = stats['total_messages']
                self._last_locations = stats['valid_locations']
            
            # Always log metrics
            logger.info(f"GPS TCP Metrics: {json.dumps(metrics)}")
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error reporting metrics: {e}")
            return {}
    
    def report_error(self, error_type: str, details: str = None):
        """Report an error event"""
        try:
            if self.datadog_enabled and self.datadog_client:
                self.datadog_client.api.Event.create(
                    title=f"GPS TCP Server Error: {error_type}",
                    text=details or error_type,
                    alert_type="error",
                    tags=["gps_tcp_server", "error", f"error_type:{error_type}"]
                )
            
            if self.prometheus_enabled:
                self.prom_errors.labels(error_type=error_type).inc()
            
            logger.error(f"GPS TCP Error [{error_type}]: {details}")
            
        except Exception as e:
            logger.error(f"Error reporting error metric: {e}")
    
    def report_device_connection(self, device_id: str, ip: str, connected: bool):
        """Report device connection/disconnection events"""
        try:
            event_type = "connected" if connected else "disconnected"
            
            if self.datadog_enabled and self.datadog_client:
                self.datadog_client.api.Event.create(
                    title=f"GPS Device {event_type}",
                    text=f"Device {device_id} from {ip} {event_type}",
                    tags=[
                        "gps_tcp_server", 
                        f"device_id:{device_id}",
                        f"event:{event_type}"
                    ]
                )
            
            logger.info(f"Device {event_type}: {device_id} from {ip}")
            
        except Exception as e:
            logger.error(f"Error reporting device event: {e}")
    
    def report_location(self, device_id: str, lat: float, lon: float, speed: float = None):
        """Report GPS location data point"""
        try:
            if self.datadog_enabled and self.datadog_client:
                tags = [
                    f"device_id:{device_id}",
                    "data_type:location"
                ]
                
                # Could send to metrics or logs
                self.datadog_client.api.Metric.send(
                    metric='gps.tcp.location.received',
                    points=1,
                    tags=tags
                )
                
                if speed is not None:
                    self.datadog_client.api.Metric.send(
                        metric='gps.tcp.device.speed',
                        points=speed,
                        tags=tags
                    )
            
        except Exception as e:
            logger.error(f"Error reporting location: {e}")
    
    def _parse_uptime(self, uptime_str: str) -> float:
        """Convert uptime string to seconds"""
        try:
            # Format: "0:02:17.999730"
            parts = uptime_str.split(':')
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                return hours * 3600 + minutes * 60 + seconds
        except:
            return 0.0


class StatsLogger:
    """Periodic stats logging for GPS TCP Server"""
    
    def __init__(self, server_instance, interval: int = 60):
        self.server = server_instance
        self.interval = interval
        self.last_report = time.time()
        self.metrics_collector = MetricsCollector(server_instance)
    
    async def periodic_report(self):
        """Called periodically to report stats"""
        current_time = time.time()
        if current_time - self.last_report >= self.interval:
            self.metrics_collector.report_metrics()
            self.last_report = current_time