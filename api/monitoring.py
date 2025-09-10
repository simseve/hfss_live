"""
Comprehensive monitoring API endpoints with Datadog integration
Provides real-time platform metrics and health status
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone
import logging
import asyncio
import time
from sqlalchemy import text, select, func
from sqlalchemy.orm import Session

from database.db_conf import get_db
from database.models import LiveTrackPoint, UploadedTrackPoint, Flight, Race
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES
from monitoring.datadog_integration import datadog_metrics
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/monitoring", tags=["Monitoring"])

async def get_platform_metrics(db: Session) -> Dict[str, Any]:
    """
    Get comprehensive platform metrics for internal use.
    This function is used by the metrics pusher background task.
    """
    monitor = PlatformMonitor()
    return await monitor.get_comprehensive_metrics(db)


class PlatformMonitor:
    """Central monitoring service for all platform components"""
    
    def __init__(self):
        self.last_metrics = {}
        self.last_update = time.time()
        self.metrics_history = []  # Store last N metric snapshots
        self.max_history = 60  # Keep 60 data points (1 hour at 1-minute intervals)
    
    async def get_comprehensive_metrics(self, db: Session) -> Dict[str, Any]:
        """Get all platform metrics for dashboard and metrics pusher"""
        try:
            live_metrics = await self.get_live_tracking_metrics(db)
            upload_metrics = await self.get_upload_metrics(db)
            scoring_metrics = await self.get_scoring_metrics()  # No db param
            gps_metrics = await self.get_gps_tcp_metrics()  # No db param
            queue_metrics = await self.get_queue_health()  # Use existing method
            db_metrics = await self.get_database_metrics(db)
            
            # Calculate platform health based on metrics
            platform_health = self._calculate_platform_health(
                live_metrics, upload_metrics, queue_metrics, db_metrics
            )
            
            return {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'live_tracking': live_metrics,
                'uploads': upload_metrics,
                'scoring': scoring_metrics,
                'gps_tcp_server': gps_metrics,
                'database': db_metrics,
                'queues': queue_metrics,
                'platform_health': platform_health
            }
        except Exception as e:
            logger.error(f"Error getting comprehensive metrics: {e}")
            raise
    
    def _calculate_platform_health(self, live_metrics: Dict, upload_metrics: Dict, 
                                  queue_metrics: Dict, db_metrics: Dict) -> Dict[str, Any]:
        """Calculate overall platform health based on metrics"""
        issues = []
        status = 'healthy'
        
        # Check queue health
        if queue_metrics.get('summary', {}).get('total_dlq', 0) > 100:
            issues.append('Critical: High DLQ count')
            status = 'critical'
        elif queue_metrics.get('summary', {}).get('total_dlq', 0) > 10:
            issues.append('Warning: DLQ items present')
            status = 'degraded' if status == 'healthy' else status
            
        # Check database connections (relaxed threshold)
        active = db_metrics.get('connections_active', 0)
        total = db_metrics.get('connections_total', 1)
        # Only trigger if using more than 95% of connections (was 90%)
        if total > 0 and (active / total) > 0.95:
            issues.append('High database connection usage')
            status = 'degraded' if status == 'healthy' else status
            
        # Check for stalled queues
        if queue_metrics.get('summary', {}).get('total_pending', 0) > 1000:
            issues.append('High queue backlog')
            status = 'degraded' if status == 'healthy' else status
            
        return {
            'status': status,
            'issues': issues,
            'components_checked': 6
        }
    
    async def get_live_tracking_metrics(self, db: Session) -> Dict[str, Any]:
        """Get metrics for live tracking system"""
        try:
            # Get active flights (last 30 minutes)
            cutoff_time = datetime.utcnow() - timedelta(minutes=30)
            active_flight_count = db.query(func.count(Flight.id))\
                .filter(Flight.created_at > cutoff_time)\
                .scalar() or 0
            
            # Get unique devices
            active_device_count = db.query(func.count(func.distinct(LiveTrackPoint.device_id)))\
                .filter(LiveTrackPoint.datetime > cutoff_time)\
                .scalar() or 0
            
            # Get point counts
            total_point_count = db.query(func.count(LiveTrackPoint.id)).scalar() or 0
            
            # Recent points (last minute)
            recent_cutoff = datetime.utcnow() - timedelta(minutes=1)
            recent_point_count = db.query(func.count(LiveTrackPoint.id))\
                .filter(LiveTrackPoint.datetime > recent_cutoff)\
                .scalar() or 0
            
            # Calculate messages per second
            messages_per_second = recent_point_count / 60.0
            
            # Queue metrics for live points
            queue_stats = await redis_queue.get_queue_stats()
            live_queue = queue_stats.get('live_points', {})
            
            metrics = {
                'active_flights': active_flight_count,
                'active_devices': active_device_count,
                'total_points': total_point_count,
                'points_last_minute': recent_point_count,
                'messages_per_second': round(messages_per_second, 2),
                'queue_pending': live_queue.get('total_pending', 0),
                'queue_processing': live_queue.get('processing', 0),
                'dlq_size': live_queue.get('dlq_size', 0)
            }
            
            # Report to Datadog
            await datadog_metrics.report_live_tracking_metrics({
                'active_flights': active_flight_count,
                'active_devices': active_device_count,
                'messages_total': total_point_count,
                'points_received': recent_point_count,
                'points_processed': recent_point_count - live_queue.get('total_pending', 0),
                'points_failed': live_queue.get('dlq_size', 0)
            })
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error getting live tracking metrics: {e}")
            return {'error': str(e)}
    
    async def get_upload_metrics(self, db: Session) -> Dict[str, Any]:
        """Get metrics for file upload system"""
        try:
            # Get upload statistics
            total_upload_count = db.query(func.count(func.distinct(UploadedTrackPoint.flight_id))).scalar() or 0
            
            # Recent uploads (last hour)
            recent_cutoff = datetime.utcnow() - timedelta(hours=1)
            recent_upload_count = db.query(func.count(func.distinct(UploadedTrackPoint.flight_id)))\
                .filter(UploadedTrackPoint.datetime > recent_cutoff)\
                .scalar() or 0
            
            # Queue metrics for uploads
            queue_stats = await redis_queue.get_queue_stats()
            upload_queue = queue_stats.get('upload_points', {})
            
            metrics = {
                'total_uploads': total_upload_count,
                'uploads_last_hour': recent_upload_count,
                'queue_pending': upload_queue.get('total_pending', 0),
                'queue_processing': upload_queue.get('processing', 0),
                'dlq_size': upload_queue.get('dlq_size', 0)
            }
            
            # Report to Datadog
            await datadog_metrics.report_upload_metrics({
                'files_uploaded': recent_upload_count,
                'files_processing': upload_queue.get('processing', 0),
                'files_completed': total_upload_count
            })
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error getting upload metrics: {e}")
            return {'error': str(e)}
    
    async def get_scoring_metrics(self) -> Dict[str, Any]:
        """Get metrics for scoring batch system"""
        try:
            # Queue metrics for scoring
            queue_stats = await redis_queue.get_queue_stats()
            scoring_queue = queue_stats.get('scoring_batch', {})
            
            metrics = {
                'queue_pending': scoring_queue.get('total_pending', 0),
                'queue_processing': scoring_queue.get('processing', 0),
                'dlq_size': scoring_queue.get('dlq_size', 0),
                'batches_processed': scoring_queue.get('processed_total', 0)
            }
            
            # Report to Datadog
            await datadog_metrics.report_scoring_metrics({
                'batches_processed': scoring_queue.get('processed_total', 0),
                'avg_batch_size': scoring_queue.get('avg_batch_size', 0),
                'errors': scoring_queue.get('dlq_size', 0)
            })
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error getting scoring metrics: {e}")
            return {'error': str(e)}
    
    async def get_gps_tcp_metrics(self) -> Dict[str, Any]:
        """Get metrics for GPS TCP server"""
        try:
            # Try to get status from GPS TCP endpoint
            metrics = {
                'status': 'unknown',
                'active_connections': 0,
                'messages_total': 0,
                'devices_total': 0
            }
            
            # Check if GPS TCP is enabled
            if settings.GPS_TCP_ENABLED:
                # TODO: Fetch actual metrics from GPS TCP server
                # This would connect to the GPS TCP server's monitoring endpoint
                metrics['status'] = 'enabled'
            else:
                metrics['status'] = 'disabled'
            
            # Report to Datadog
            await datadog_metrics.report_gps_tcp_metrics(metrics)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error getting GPS TCP metrics: {e}")
            return {'error': str(e)}
    
    async def get_database_metrics(self, db: Session) -> Dict[str, Any]:
        """Get database performance metrics"""
        try:
            # Get connection pool stats
            pool = db.bind.pool if hasattr(db, 'bind') else None
            if pool:
                metrics = {
                    'connections_active': pool.size() if hasattr(pool, 'size') else 0,
                    'connections_idle': pool.checkedin() if hasattr(pool, 'checkedin') else 0,
                    'connections_total': pool.size() if hasattr(pool, 'size') else 0
                }
            else:
                metrics = {
                    'connections_active': 0,
                    'connections_idle': 0,
                    'connections_total': 0
                }
            
            # Get table sizes
            table_sizes = {}
            tables = ['live_track_points', 'uploaded_track_points', 'flights', 'races']
            for table in tables:
                result = db.execute(
                    text(f"SELECT COUNT(*) FROM {table}")
                )
                table_sizes[table] = result.scalar() or 0
            
            metrics['table_sizes'] = table_sizes
            
            # Check TimescaleDB compression
            try:
                compression_result = db.execute(
                    text("""
                        SELECT hypertable_name, 
                               before_compression_total_bytes,
                               after_compression_total_bytes
                        FROM timescaledb_information.compression_stats
                        WHERE hypertable_name IN ('live_track_points', 'uploaded_track_points')
                    """)
                )
                compression_stats = []
                for row in compression_result:
                    if row.before_compression_total_bytes:
                        compression_ratio = 1 - (row.after_compression_total_bytes / row.before_compression_total_bytes)
                        compression_stats.append({
                            'table': row.hypertable_name,
                            'compression_ratio': round(compression_ratio * 100, 2)
                        })
                metrics['compression'] = compression_stats
            except:
                pass  # TimescaleDB might not be available
            
            # Report to Datadog
            await datadog_metrics.report_database_metrics({
                'active_connections': metrics['connections_active'],
                'idle_connections': metrics['connections_idle'],
                'table_sizes': table_sizes
            })
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error getting database metrics: {e}")
            return {'error': str(e)}
    
    async def get_queue_health(self) -> Dict[str, Any]:
        """Get detailed queue health for all queues"""
        try:
            all_queues = {}
            total_pending = 0
            total_dlq = 0
            
            for queue_type, queue_name in QUEUE_NAMES.items():
                # Get queue stats
                stats = await redis_queue.get_queue_stats()
                queue_stats = stats.get(queue_type, {})
                
                # Get DLQ size
                dlq_size = await redis_queue.redis_client.zcard(f"dlq:{queue_name}")
                
                # Get processing stats
                processing_key = f"processing:{queue_name}"
                processing_count = await redis_queue.redis_client.scard(processing_key)
                
                # Calculate health status
                health_status = 'healthy'
                if dlq_size > 100:
                    health_status = 'critical'
                elif dlq_size > 10:
                    health_status = 'degraded'
                elif queue_stats.get('total_pending', 0) > 5000:
                    health_status = 'degraded'
                
                queue_health = {
                    'pending': queue_stats.get('total_pending', 0),
                    'processing': processing_count,
                    'dlq_size': dlq_size,
                    'status': health_status,
                    'processed_total': queue_stats.get('processed_total', 0),
                    'failed_total': queue_stats.get('failed_total', 0)
                }
                
                all_queues[queue_type] = queue_health
                total_pending += queue_health['pending']
                total_dlq += dlq_size
            
            # Overall health
            overall_status = 'healthy'
            if total_dlq > 100:
                overall_status = 'critical'
            elif total_dlq > 10 or total_pending > 10000:
                overall_status = 'degraded'
            
            health = {
                'status': overall_status,
                'queues': all_queues,
                'summary': {
                    'total_pending': total_pending,
                    'total_dlq': total_dlq
                }
            }
            
            # Report to Datadog
            await datadog_metrics.report_queue_metrics(all_queues)
            
            return health
            
        except Exception as e:
            logger.error(f"Error getting queue health: {e}")
            return {'error': str(e), 'status': 'unknown'}


# Create global monitor instance
platform_monitor = PlatformMonitor()


@router.get("/dashboard")
async def get_monitoring_dashboard(
    db: Session = Depends(get_db),
    include_history: bool = Query(False, description="Include historical metrics")
) -> Dict[str, Any]:
    """
    Get comprehensive monitoring dashboard with all platform metrics
    
    Returns real-time metrics for:
    - Live tracking (active flights, devices, messages/sec)
    - Upload system status
    - Scoring batch processing
    - GPS TCP server status
    - Queue health and dead letter queues
    - Database performance
    """
    try:
        # Collect all metrics in parallel
        metrics_tasks = [
            platform_monitor.get_live_tracking_metrics(db),
            platform_monitor.get_upload_metrics(db),
            platform_monitor.get_scoring_metrics(),
            platform_monitor.get_gps_tcp_metrics(),
            platform_monitor.get_database_metrics(db),
            platform_monitor.get_queue_health()
        ]
        
        results = await asyncio.gather(*metrics_tasks, return_exceptions=True)
        
        # Build dashboard
        dashboard = {
            'timestamp': datetime.utcnow().isoformat(),
            'live_tracking': results[0] if not isinstance(results[0], Exception) else {'error': str(results[0])},
            'uploads': results[1] if not isinstance(results[1], Exception) else {'error': str(results[1])},
            'scoring': results[2] if not isinstance(results[2], Exception) else {'error': str(results[2])},
            'gps_tcp_server': results[3] if not isinstance(results[3], Exception) else {'error': str(results[3])},
            'database': results[4] if not isinstance(results[4], Exception) else {'error': str(results[4])},
            'queues': results[5] if not isinstance(results[5], Exception) else {'error': str(results[5])}
        }
        
        # Calculate overall platform health
        queue_health = dashboard['queues']
        overall_status = 'healthy'
        issues = []
        
        if queue_health.get('status') == 'critical':
            overall_status = 'critical'
            issues.append('Queue system has critical issues')
        elif queue_health.get('status') == 'degraded':
            overall_status = 'degraded'
            issues.append('Queue system is degraded')
        
        # Check for high DLQ counts
        if queue_health.get('summary', {}).get('total_dlq', 0) > 0:
            issues.append(f"Dead letter queue has {queue_health['summary']['total_dlq']} items")
        
        # Check database connections (increased threshold with new pool size)
        db_metrics = dashboard['database']
        if db_metrics.get('connections_active', 0) > 190:  # 95% of 200 total (100 pool + 100 overflow)
            if overall_status == 'healthy':
                overall_status = 'degraded'
            issues.append('High database connection usage')
        
        dashboard['platform_health'] = {
            'status': overall_status,
            'issues': issues,
            'components_checked': len(results)
        }
        
        # Add historical data if requested
        if include_history:
            dashboard['history'] = platform_monitor.metrics_history[-10:]  # Last 10 snapshots
        
        # Store current metrics in history
        platform_monitor.metrics_history.append({
            'timestamp': dashboard['timestamp'],
            'live_messages_per_sec': dashboard['live_tracking'].get('messages_per_second', 0),
            'total_pending': queue_health.get('summary', {}).get('total_pending', 0),
            'total_dlq': queue_health.get('summary', {}).get('total_dlq', 0)
        })
        
        # Limit history size
        if len(platform_monitor.metrics_history) > platform_monitor.max_history:
            platform_monitor.metrics_history = platform_monitor.metrics_history[-platform_monitor.max_history:]
        
        # Report overall health to Datadog
        await datadog_metrics.report_system_health({
            'status': overall_status,
            'message': '; '.join(issues) if issues else 'All systems operational',
            'components': {
                'live_tracking': {'status': 'healthy' if 'error' not in dashboard['live_tracking'] else 'critical'},
                'uploads': {'status': 'healthy' if 'error' not in dashboard['uploads'] else 'critical'},
                'scoring': {'status': 'healthy' if 'error' not in dashboard['scoring'] else 'critical'},
                'gps_tcp': {'status': 'healthy' if dashboard['gps_tcp_server'].get('status') != 'error' else 'critical'},
                'database': {'status': 'healthy' if 'error' not in dashboard['database'] else 'critical'},
                'queues': {'status': queue_health.get('status', 'unknown')}
            }
        })
        
        return dashboard
        
    except Exception as e:
        logger.error(f"Error building monitoring dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/live")
async def get_live_metrics(
    db: Session = Depends(get_db),
    window_minutes: int = Query(5, ge=1, le=60, description="Time window in minutes")
) -> Dict[str, Any]:
    """Get detailed live tracking metrics"""
    metrics = await platform_monitor.get_live_tracking_metrics(db)
    metrics['window_minutes'] = window_minutes
    metrics['timestamp'] = datetime.utcnow().isoformat()
    return metrics


@router.get("/metrics/queues")
async def get_queue_metrics() -> Dict[str, Any]:
    """Get detailed queue metrics including DLQ status"""
    health = await platform_monitor.get_queue_health()
    health['timestamp'] = datetime.utcnow().isoformat()
    return health


@router.get("/metrics/devices")
async def get_device_metrics(
    db: Session = Depends(get_db),
    active_only: bool = Query(True, description="Show only active devices")
) -> Dict[str, Any]:
    """Get per-device metrics and status"""
    try:
        cutoff_time = datetime.utcnow() - timedelta(minutes=30 if active_only else 24*60)
        
        # Get device statistics - join with flights to get device_id
        device_stats = db.execute(
            text("""
                SELECT 
                    f.device_id,
                    f.flight_id,
                    f.pilot_name,
                    COUNT(ltp.*) as point_count,
                    MAX(ltp.datetime) as last_seen,
                    MIN(ltp.datetime) as first_seen,
                    AVG(ltp.elevation) as avg_elevation,
                    MAX(ltp.elevation) as max_elevation
                FROM live_track_points ltp
                JOIN flights f ON ltp.flight_uuid = f.id
                WHERE ltp.datetime > :cutoff
                GROUP BY f.device_id, f.flight_id, f.pilot_name
                ORDER BY last_seen DESC
                LIMIT 100
            """),
            {'cutoff': cutoff_time}
        )
        
        devices = []
        for row in device_stats:
            devices.append({
                'device_id': row.device_id,
                'flight_id': row.flight_id,
                'pilot_name': row.pilot_name,
                'point_count': row.point_count,
                'last_seen': row.last_seen.isoformat() if row.last_seen else None,
                'first_seen': row.first_seen.isoformat() if row.first_seen else None,
                'avg_elevation': float(row.avg_elevation) if row.avg_elevation else 0,
                'max_elevation': float(row.max_elevation) if row.max_elevation else 0,
                'status': 'active' if row.last_seen and (datetime.now(timezone.utc) - (row.last_seen.replace(tzinfo=timezone.utc) if row.last_seen.tzinfo is None else row.last_seen)).seconds < 300 else 'inactive'
            })
        
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'total_devices': len(devices),
            'active_devices': sum(1 for d in devices if d['status'] == 'active'),
            'devices': devices
        }
        
    except Exception as e:
        logger.error(f"Error getting device metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alert/test")
async def test_alert_system(
    alert_type: str = Query("info", regex="^(info|warning|error|critical)$"),
    message: str = Query("Test alert from monitoring system")
) -> Dict[str, Any]:
    """Test the alert system by sending a test alert to Datadog"""
    try:
        await datadog_metrics.send_event(
            title=f"Test Alert: {alert_type.upper()}",
            text=message,
            alert_type=alert_type,
            tags=["test", "monitoring"]
        )
        
        return {
            'status': 'sent',
            'alert_type': alert_type,
            'message': message,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error sending test alert: {e}")
        raise HTTPException(status_code=500, detail=str(e))