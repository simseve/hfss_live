"""
Background task to periodically push metrics to Datadog
"""
import asyncio
import logging
import time
from typing import Optional
from datetime import datetime
from datadog import DogStatsd
from sqlalchemy.orm import Session
from database.db_conf import get_db
from config import settings

logger = logging.getLogger(__name__)

class MetricsPusher:
    """Periodically pushes platform metrics to Datadog"""
    
    def __init__(self, interval: int = 60):
        """
        Initialize metrics pusher
        
        Args:
            interval: Seconds between metric pushes (default 60)
        """
        self.interval = interval
        self.statsd_client = None
        self.running = False
        self._task = None
        self._initialize_statsd()
    
    def _initialize_statsd(self):
        """Initialize StatsD client"""
        # Only initialize Datadog in production
        if not settings.PROD:
            logger.info("MetricsPusher: Disabled in development mode")
            self.statsd_client = None
            return
            
        try:
            self.statsd_client = DogStatsd(
                host=settings.DD_AGENT_HOST,
                port=settings.DD_DOGSTATSD_PORT,
                namespace='hfss',
                constant_tags=[
                    f'env:{settings.DD_ENV or "production"}',
                    f'version:{settings.DD_VERSION or "1.0.0"}'
                ]
            )
            logger.info(f"MetricsPusher: StatsD client initialized - {settings.DD_AGENT_HOST}:{settings.DD_DOGSTATSD_PORT}")
        except Exception as e:
            logger.error(f"MetricsPusher: Failed to initialize StatsD - {e}")
            self.statsd_client = None
    
    async def start(self):
        """Start the background metrics pusher"""
        if self.running:
            logger.warning("MetricsPusher: Already running")
            return
        
        self.running = True
        self._task = asyncio.create_task(self._push_metrics_loop())
        logger.info(f"MetricsPusher: Started with {self.interval}s interval")
    
    async def stop(self):
        """Stop the background metrics pusher"""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MetricsPusher: Stopped")
    
    async def _push_metrics_loop(self):
        """Main loop that pushes metrics periodically"""
        while self.running:
            try:
                await self._push_metrics()
            except Exception as e:
                logger.error(f"MetricsPusher: Error pushing metrics - {e}")
            
            # Wait for next interval
            await asyncio.sleep(self.interval)
    
    async def _push_metrics(self):
        """Push current platform metrics to Datadog"""
        if not self.statsd_client:
            # Silent when disabled in development
            return
        
        try:
            # Import here to avoid circular dependency
            from api.monitoring import get_platform_metrics
            
            # Get current metrics
            db = next(get_db())
            metrics = await get_platform_metrics(db)
            db.close()
            
            # Push live tracking metrics
            live = metrics.get('live_tracking', {})
            self.statsd_client.gauge('live.active_flights', live.get('active_flights', 0))
            self.statsd_client.gauge('live.active_devices', live.get('active_devices', 0))
            self.statsd_client.gauge('live.total_points', live.get('total_points', 0))
            self.statsd_client.gauge('live.messages_per_second', live.get('messages_per_second', 0))
            self.statsd_client.gauge('queue.pending', live.get('queue_pending', 0), tags=['queue_type:live'])
            self.statsd_client.gauge('queue.processing', live.get('queue_processing', 0), tags=['queue_type:live'])
            self.statsd_client.gauge('queue.dlq_size', live.get('dlq_size', 0), tags=['queue_type:live'])
            
            # Push upload metrics
            uploads = metrics.get('uploads', {})
            self.statsd_client.gauge('uploads.total', uploads.get('total_uploads', 0))
            self.statsd_client.gauge('uploads.last_hour', uploads.get('uploads_last_hour', 0))
            self.statsd_client.gauge('queue.pending', uploads.get('queue_pending', 0), tags=['queue_type:upload'])
            self.statsd_client.gauge('queue.dlq_size', uploads.get('dlq_size', 0), tags=['queue_type:upload'])
            
            # Push scoring metrics
            scoring = metrics.get('scoring', {})
            self.statsd_client.gauge('queue.pending', scoring.get('queue_pending', 0), tags=['queue_type:scoring'])
            self.statsd_client.gauge('queue.dlq_size', scoring.get('dlq_size', 0), tags=['queue_type:scoring'])
            self.statsd_client.gauge('scoring.batches_processed', scoring.get('batches_processed', 0))
            
            # Push GPS TCP metrics
            gps = metrics.get('gps_tcp_server', {})
            self.statsd_client.gauge('gps_tcp.active_connections', gps.get('active_connections', 0))
            self.statsd_client.gauge('gps_tcp.messages_total', gps.get('messages_total', 0))
            self.statsd_client.gauge('gps_tcp.devices_total', gps.get('devices_total', 0))
            
            # Push database metrics
            db_metrics = metrics.get('database', {})
            self.statsd_client.gauge('database.connections_active', db_metrics.get('connections_active', 0))
            self.statsd_client.gauge('database.connections_idle', db_metrics.get('connections_idle', 0))
            self.statsd_client.gauge('database.connections_total', db_metrics.get('connections_total', 0))
            
            # Table sizes
            table_sizes = db_metrics.get('table_sizes', {})
            for table, size in table_sizes.items():
                self.statsd_client.gauge('database.table_size', size, tags=[f'table:{table}'])
            
            # Push queue summary metrics
            queues = metrics.get('queues', {})
            summary = queues.get('summary', {})
            self.statsd_client.gauge('queue.total_pending', summary.get('total_pending', 0))
            self.statsd_client.gauge('queue.total_dlq', summary.get('total_dlq', 0))
            
            # Platform health
            health = metrics.get('platform_health', {})
            health_value = 1 if health.get('status') == 'healthy' else 0
            self.statsd_client.gauge('platform.health', health_value)
            
            # Send event if platform is degraded
            if health.get('status') != 'healthy' and health.get('issues'):
                self.statsd_client.event(
                    'Platform Health Degraded',
                    f"Status: {health.get('status')}. Issues: {', '.join(health.get('issues', []))}",
                    alert_type='warning',
                    tags=['service:hfss-live']
                )
            
            logger.debug(f"MetricsPusher: Pushed metrics - {live.get('messages_per_second', 0)} msg/s, {live.get('active_flights', 0)} flights")
            
        except Exception as e:
            logger.error(f"MetricsPusher: Failed to push metrics - {e}", exc_info=True)

# Global instance
metrics_pusher = MetricsPusher(interval=60)

async def start_metrics_pusher():
    """Start the global metrics pusher"""
    await metrics_pusher.start()

async def stop_metrics_pusher():
    """Stop the global metrics pusher"""
    await metrics_pusher.stop()