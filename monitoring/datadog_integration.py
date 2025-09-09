"""
Comprehensive Datadog Integration for HFSS Live Platform
Monitors all critical components: live tracking, uploads, scoring, GPS server, queues
"""
import os
import time
import logging
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import json

logger = logging.getLogger(__name__)


class DatadogMetrics:
    """Centralized Datadog metrics collector for HFSS platform"""
    
    def __init__(self):
        self.enabled = False
        self.statsd_client = None
        self.datadog_api = None
        self.initialized = False
        
        # Metric prefixes for different components
        self.prefixes = {
            'live': 'hfss.live',
            'upload': 'hfss.upload', 
            'scoring': 'hfss.scoring',
            'gps': 'hfss.gps_tcp',
            'queue': 'hfss.queue',
            'db': 'hfss.database',
            'api': 'hfss.api'
        }
        
        # Track metrics over time for rate calculations
        self.last_metrics = {}
        self.last_update = time.time()
        
    async def initialize(self):
        """Initialize Datadog clients"""
        try:
            # Try DogStatsD first (preferred for metrics)
            from datadog import DogStatsd, initialize, api
            from config import settings
            
            # Initialize with settings
            dd_host = settings.DD_AGENT_HOST
            dd_port = settings.DD_DOGSTATSD_PORT
            
            self.statsd_client = DogStatsd(
                host=dd_host,
                port=dd_port,
                constant_tags=[
                    f"env:{settings.DD_ENV}",
                    f"service:hfss-live",
                    f"version:{settings.DD_VERSION}",
                    f"region:{os.getenv('AWS_REGION', 'us-east-1')}"
                ]
            )
            
            # Initialize API client for events and service checks
            if settings.DD_API_KEY:
                initialize(
                    api_key=settings.DD_API_KEY,
                    app_key=settings.DD_APP_KEY,
                    api_host='https://api.datadoghq.eu'  # EU site
                )
                self.datadog_api = api
            
            self.enabled = bool(settings.DD_API_KEY)
            self.initialized = True
            
            if self.enabled:
                logger.info("Datadog integration initialized successfully")
                await self.send_event(
                    "HFSS Platform Started",
                    "Platform monitoring initialized",
                    alert_type="info"
                )
            else:
                logger.warning("Datadog API key not configured - metrics will be logged only")
                
        except ImportError:
            logger.warning("Datadog library not installed - install with: pip install datadog")
        except Exception as e:
            logger.error(f"Failed to initialize Datadog: {e}")
    
    def gauge(self, metric: str, value: float, tags: List[str] = None):
        """Send gauge metric"""
        if self.statsd_client:
            self.statsd_client.gauge(metric, value, tags=tags)
        else:
            logger.debug(f"Gauge: {metric}={value} tags={tags}")
    
    def increment(self, metric: str, value: float = 1, tags: List[str] = None):
        """Send counter increment"""
        if self.statsd_client:
            self.statsd_client.increment(metric, value, tags=tags)
        else:
            logger.debug(f"Increment: {metric}+{value} tags={tags}")
    
    def histogram(self, metric: str, value: float, tags: List[str] = None):
        """Send histogram/distribution metric"""
        if self.statsd_client:
            self.statsd_client.histogram(metric, value, tags=tags)
        else:
            logger.debug(f"Histogram: {metric}={value} tags={tags}")
    
    def timing(self, metric: str, value: float, tags: List[str] = None):
        """Send timing metric (in milliseconds)"""
        if self.statsd_client:
            self.statsd_client.timing(metric, value, tags=tags)
        else:
            logger.debug(f"Timing: {metric}={value}ms tags={tags}")
    
    @asynccontextmanager
    async def timed(self, metric: str, tags: List[str] = None):
        """Context manager for timing operations"""
        start = time.time()
        try:
            yield
        finally:
            elapsed_ms = (time.time() - start) * 1000
            self.timing(metric, elapsed_ms, tags=tags)
    
    async def send_event(self, title: str, text: str, alert_type: str = "info", tags: List[str] = None):
        """Send event to Datadog"""
        if self.datadog_api and self.enabled:
            try:
                self.datadog_api.Event.create(
                    title=title,
                    text=text,
                    alert_type=alert_type,
                    tags=tags or []
                )
            except Exception as e:
                logger.error(f"Failed to send Datadog event: {e}")
        else:
            logger.info(f"Event: [{alert_type}] {title} - {text}")
    
    async def service_check(self, check_name: str, status: int, message: str = None, tags: List[str] = None):
        """Send service check (0=OK, 1=WARNING, 2=CRITICAL, 3=UNKNOWN)"""
        if self.statsd_client:
            self.statsd_client.service_check(check_name, status, message=message, tags=tags)
        else:
            status_names = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}
            logger.info(f"Service Check: {check_name} = {status_names.get(status, status)} - {message}")
    
    async def report_queue_metrics(self, queue_stats: Dict[str, Any]):
        """Report queue-specific metrics"""
        for queue_type, stats in queue_stats.items():
            tags = [f"queue_type:{queue_type}"]
            
            # Queue sizes
            self.gauge(f"{self.prefixes['queue']}.pending", stats.get('pending', 0), tags)
            self.gauge(f"{self.prefixes['queue']}.processing", stats.get('processing', 0), tags)
            self.gauge(f"{self.prefixes['queue']}.dlq_size", stats.get('dlq_size', 0), tags)
            
            # Processing metrics
            if 'processed_last_minute' in stats:
                self.gauge(f"{self.prefixes['queue']}.throughput", stats['processed_last_minute'], tags)
            
            # Error metrics
            if stats.get('dlq_size', 0) > 0:
                self.increment(f"{self.prefixes['queue']}.dlq_items", stats['dlq_size'], tags)
                
                # Alert on DLQ threshold
                if stats['dlq_size'] > 100:
                    await self.send_event(
                        f"High DLQ Count: {queue_type}",
                        f"Dead letter queue has {stats['dlq_size']} items",
                        alert_type="error",
                        tags=tags
                    )
    
    async def report_live_tracking_metrics(self, metrics: Dict[str, Any]):
        """Report live tracking metrics"""
        prefix = self.prefixes['live']
        
        # Active flights and devices
        self.gauge(f"{prefix}.active_flights", metrics.get('active_flights', 0))
        self.gauge(f"{prefix}.active_devices", metrics.get('active_devices', 0))
        
        # Messages per second
        if 'messages_total' in metrics:
            current_time = time.time()
            if 'messages_total' in self.last_metrics:
                time_diff = current_time - self.last_update
                msg_diff = metrics['messages_total'] - self.last_metrics['messages_total']
                msg_per_sec = msg_diff / time_diff if time_diff > 0 else 0
                self.gauge(f"{prefix}.messages_per_second", msg_per_sec)
            
            self.last_metrics['messages_total'] = metrics['messages_total']
            self.last_update = current_time
        
        # Track point metrics
        self.increment(f"{prefix}.points_received", metrics.get('points_received', 0))
        self.increment(f"{prefix}.points_processed", metrics.get('points_processed', 0))
        self.increment(f"{prefix}.points_failed", metrics.get('points_failed', 0))
        
        # Latency metrics
        if 'avg_latency_ms' in metrics:
            self.histogram(f"{prefix}.latency", metrics['avg_latency_ms'])
    
    async def report_upload_metrics(self, metrics: Dict[str, Any]):
        """Report file upload metrics"""
        prefix = self.prefixes['upload']
        
        self.increment(f"{prefix}.files_uploaded", metrics.get('files_uploaded', 0))
        self.gauge(f"{prefix}.files_processing", metrics.get('files_processing', 0))
        self.increment(f"{prefix}.files_completed", metrics.get('files_completed', 0))
        self.increment(f"{prefix}.files_failed", metrics.get('files_failed', 0))
        
        # File size metrics
        if 'avg_file_size_mb' in metrics:
            self.histogram(f"{prefix}.file_size_mb", metrics['avg_file_size_mb'])
        
        # Processing time
        if 'avg_processing_time_sec' in metrics:
            self.histogram(f"{prefix}.processing_time", metrics['avg_processing_time_sec'] * 1000)
    
    async def report_scoring_metrics(self, metrics: Dict[str, Any]):
        """Report scoring batch metrics"""
        prefix = self.prefixes['scoring']
        
        self.increment(f"{prefix}.batches_processed", metrics.get('batches_processed', 0))
        self.gauge(f"{prefix}.batch_size", metrics.get('avg_batch_size', 0))
        self.histogram(f"{prefix}.batch_processing_time", metrics.get('processing_time_ms', 0))
        
        # Scoring results
        self.increment(f"{prefix}.flights_scored", metrics.get('flights_scored', 0))
        self.increment(f"{prefix}.scoring_errors", metrics.get('errors', 0))
        
        # Performance metrics
        if 'points_per_second' in metrics:
            self.gauge(f"{prefix}.points_per_second", metrics['points_per_second'])
    
    async def report_gps_tcp_metrics(self, metrics: Dict[str, Any]):
        """Report GPS TCP server metrics"""
        prefix = self.prefixes['gps']
        
        # Connection metrics
        self.gauge(f"{prefix}.active_connections", metrics.get('active_connections', 0))
        self.increment(f"{prefix}.connections_total", metrics.get('connections_total', 0))
        self.increment(f"{prefix}.connections_failed", metrics.get('connections_failed', 0))
        
        # Device metrics
        self.gauge(f"{prefix}.active_devices", metrics.get('active_devices', 0))
        self.gauge(f"{prefix}.blacklisted_ips", metrics.get('blacklisted_ips', 0))
        
        # Message metrics
        self.increment(f"{prefix}.messages_received", metrics.get('messages_received', 0))
        self.increment(f"{prefix}.messages_parsed", metrics.get('messages_parsed', 0))
        self.increment(f"{prefix}.messages_invalid", metrics.get('messages_invalid', 0))
        
        # GPS data metrics
        self.increment(f"{prefix}.locations_received", metrics.get('locations_received', 0))
        self.increment(f"{prefix}.locations_valid", metrics.get('locations_valid', 0))
        
        # Calculate messages per second
        if 'messages_total' in metrics:
            current_time = time.time()
            if 'gps_messages_total' in self.last_metrics:
                time_diff = current_time - self.last_update
                msg_diff = metrics['messages_total'] - self.last_metrics['gps_messages_total']
                msg_per_sec = msg_diff / time_diff if time_diff > 0 else 0
                self.gauge(f"{prefix}.messages_per_second", msg_per_sec)
            
            self.last_metrics['gps_messages_total'] = metrics['messages_total']
    
    async def report_database_metrics(self, metrics: Dict[str, Any]):
        """Report database performance metrics"""
        prefix = self.prefixes['db']
        
        # Connection pool metrics
        self.gauge(f"{prefix}.connections_active", metrics.get('active_connections', 0))
        self.gauge(f"{prefix}.connections_idle", metrics.get('idle_connections', 0))
        self.gauge(f"{prefix}.connections_waiting", metrics.get('waiting_connections', 0))
        
        # Query performance
        if 'query_latency_ms' in metrics:
            self.histogram(f"{prefix}.query_latency", metrics['query_latency_ms'])
        
        # Table sizes (for monitoring growth)
        for table, size in metrics.get('table_sizes', {}).items():
            self.gauge(f"{prefix}.table_size", size, tags=[f"table:{table}"])
        
        # Replication lag (if using read replicas)
        if 'replication_lag_seconds' in metrics:
            self.gauge(f"{prefix}.replication_lag", metrics['replication_lag_seconds'])
    
    async def report_api_metrics(self, endpoint: str, method: str, status_code: int, response_time_ms: float):
        """Report API endpoint metrics"""
        prefix = self.prefixes['api']
        tags = [
            f"endpoint:{endpoint}",
            f"method:{method}",
            f"status:{status_code}",
            f"status_family:{status_code // 100}xx"
        ]
        
        # Request count
        self.increment(f"{prefix}.requests", tags=tags)
        
        # Response time
        self.histogram(f"{prefix}.response_time", response_time_ms, tags=tags)
        
        # Error tracking
        if status_code >= 400:
            self.increment(f"{prefix}.errors", tags=tags)
            
            if status_code >= 500:
                await self.send_event(
                    f"API Error: {method} {endpoint}",
                    f"Endpoint returned {status_code}",
                    alert_type="error",
                    tags=tags
                )
    
    async def report_system_health(self, health_data: Dict[str, Any]):
        """Report overall system health metrics"""
        # Overall health status
        status_map = {"healthy": 0, "degraded": 1, "critical": 2}
        status_value = status_map.get(health_data.get('status', 'unknown'), 3)
        
        await self.service_check(
            "hfss.platform.health",
            status_value,
            message=health_data.get('message', ''),
            tags=[f"component:platform"]
        )
        
        # Component health checks
        for component, component_health in health_data.get('components', {}).items():
            component_status = status_map.get(component_health.get('status', 'unknown'), 3)
            await self.service_check(
                f"hfss.{component}.health",
                component_status,
                message=component_health.get('message', ''),
                tags=[f"component:{component}"]
            )


# Global instance
datadog_metrics = DatadogMetrics()


async def initialize_datadog():
    """Initialize Datadog integration"""
    await datadog_metrics.initialize()
    return datadog_metrics


class DatadogMiddleware:
    """FastAPI middleware for automatic API metrics collection"""
    
    def __init__(self, app, metrics_client: DatadogMetrics):
        self.app = app
        self.metrics = metrics_client
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        start_time = time.time()
        
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                elapsed_ms = (time.time() - start_time) * 1000
                
                # Extract request details
                path = scope["path"]
                method = scope["method"]
                status_code = message["status"]
                
                # Report metrics
                await self.metrics.report_api_metrics(
                    endpoint=path,
                    method=method,
                    status_code=status_code,
                    response_time_ms=elapsed_ms
                )
            
            await send(message)
        
        await self.app(scope, receive, send_wrapper)