"""
Alert rules and thresholds for Datadog monitoring
Configurable alerting based on platform metrics
"""
import os
from typing import Dict, Any, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class AlertRules:
    """Define alerting rules and thresholds"""
    
    def __init__(self):
        from config import settings
        
        # Queue thresholds
        self.queue_thresholds = {
            'pending_warning': settings.ALERT_QUEUE_PENDING_WARN,
            'pending_critical': settings.ALERT_QUEUE_PENDING_CRIT,
            'dlq_warning': settings.ALERT_DLQ_WARN,
            'dlq_critical': settings.ALERT_DLQ_CRIT,
            'processing_lag_seconds': settings.ALERT_PROCESSING_LAG
        }
        
        # Live tracking thresholds
        self.live_thresholds = {
            'no_data_minutes': settings.ALERT_NO_DATA_MINUTES,
            'error_rate_percent': settings.ALERT_ERROR_RATE,
            'latency_ms_warning': settings.ALERT_LATENCY_WARN,
            'latency_ms_critical': settings.ALERT_LATENCY_CRIT
        }
        
        # GPS TCP thresholds
        self.gps_thresholds = {
            'blacklist_count_warning': int(os.getenv('ALERT_BLACKLIST_WARN', 5)),
            'blacklist_count_critical': int(os.getenv('ALERT_BLACKLIST_CRIT', 20)),
            'connection_failures_per_minute': int(os.getenv('ALERT_CONN_FAIL', 10)),
            'invalid_message_rate': float(os.getenv('ALERT_INVALID_MSG_RATE', 10.0))
        }
        
        # Database thresholds
        self.database_thresholds = {
            'connection_pool_warning': int(os.getenv('ALERT_DB_CONN_WARN', 80)),
            'connection_pool_critical': int(os.getenv('ALERT_DB_CONN_CRIT', 95)),
            'query_latency_ms': int(os.getenv('ALERT_QUERY_LATENCY', 1000)),
            'replication_lag_seconds': int(os.getenv('ALERT_REPLICATION_LAG', 10))
        }
        
        # API thresholds
        self.api_thresholds = {
            'error_rate_percent': float(os.getenv('ALERT_API_ERROR_RATE', 1.0)),
            'response_time_ms_p95': int(os.getenv('ALERT_API_P95_LATENCY', 2000)),
            'rate_limit_hits_per_minute': int(os.getenv('ALERT_RATE_LIMIT', 100))
        }
        
        # Store recent alerts to prevent spam
        self.recent_alerts = {}
        self.alert_cooldown_minutes = 15
    
    def should_alert(self, alert_key: str) -> bool:
        """Check if we should send an alert (with cooldown)"""
        now = datetime.utcnow()
        if alert_key in self.recent_alerts:
            last_alert = self.recent_alerts[alert_key]
            if (now - last_alert) < timedelta(minutes=self.alert_cooldown_minutes):
                return False
        
        self.recent_alerts[alert_key] = now
        return True
    
    def check_queue_alerts(self, queue_metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check queue metrics and generate alerts"""
        alerts = []
        
        for queue_type, metrics in queue_metrics.items():
            # Check pending items
            pending = metrics.get('pending', 0)
            if pending > self.queue_thresholds['pending_critical']:
                if self.should_alert(f"queue_{queue_type}_pending_critical"):
                    alerts.append({
                        'severity': 'critical',
                        'title': f'Critical: Queue {queue_type} backlog',
                        'message': f'{pending} items pending in {queue_type} queue',
                        'tags': ['queue', f'queue:{queue_type}', 'critical']
                    })
            elif pending > self.queue_thresholds['pending_warning']:
                if self.should_alert(f"queue_{queue_type}_pending_warning"):
                    alerts.append({
                        'severity': 'warning',
                        'title': f'Warning: Queue {queue_type} growing',
                        'message': f'{pending} items pending in {queue_type} queue',
                        'tags': ['queue', f'queue:{queue_type}', 'warning']
                    })
            
            # Check DLQ
            dlq_size = metrics.get('dlq_size', 0)
            if dlq_size > self.queue_thresholds['dlq_critical']:
                if self.should_alert(f"queue_{queue_type}_dlq_critical"):
                    alerts.append({
                        'severity': 'critical',
                        'title': f'Critical: Dead Letter Queue for {queue_type}',
                        'message': f'{dlq_size} failed items in DLQ for {queue_type}',
                        'tags': ['dlq', f'queue:{queue_type}', 'critical']
                    })
            elif dlq_size > self.queue_thresholds['dlq_warning']:
                if self.should_alert(f"queue_{queue_type}_dlq_warning"):
                    alerts.append({
                        'severity': 'warning',
                        'title': f'Warning: Items in DLQ for {queue_type}',
                        'message': f'{dlq_size} items in DLQ for {queue_type}',
                        'tags': ['dlq', f'queue:{queue_type}', 'warning']
                    })
        
        return alerts
    
    def check_live_tracking_alerts(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check live tracking metrics and generate alerts"""
        alerts = []
        
        # Check for no data
        messages_per_second = metrics.get('messages_per_second', 0)
        if messages_per_second == 0:
            if self.should_alert("live_no_data"):
                alerts.append({
                    'severity': 'warning',
                    'title': 'No live tracking data',
                    'message': 'No messages received in the last minute',
                    'tags': ['live_tracking', 'no_data']
                })
        
        # Check error rate
        total_received = metrics.get('points_received', 1)
        failed = metrics.get('points_failed', 0)
        error_rate = (failed / total_received) * 100 if total_received > 0 else 0
        
        if error_rate > self.live_thresholds['error_rate_percent']:
            if self.should_alert("live_high_error_rate"):
                alerts.append({
                    'severity': 'warning',
                    'title': 'High error rate in live tracking',
                    'message': f'Error rate: {error_rate:.1f}% ({failed}/{total_received} failed)',
                    'tags': ['live_tracking', 'errors']
                })
        
        # Check latency
        latency = metrics.get('avg_latency_ms', 0)
        if latency > self.live_thresholds['latency_ms_critical']:
            if self.should_alert("live_latency_critical"):
                alerts.append({
                    'severity': 'critical',
                    'title': 'Critical: High latency in live tracking',
                    'message': f'Average latency: {latency}ms',
                    'tags': ['live_tracking', 'latency', 'critical']
                })
        elif latency > self.live_thresholds['latency_ms_warning']:
            if self.should_alert("live_latency_warning"):
                alerts.append({
                    'severity': 'warning',
                    'title': 'Warning: Elevated latency in live tracking',
                    'message': f'Average latency: {latency}ms',
                    'tags': ['live_tracking', 'latency', 'warning']
                })
        
        return alerts
    
    def check_gps_tcp_alerts(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check GPS TCP server metrics and generate alerts"""
        alerts = []
        
        # Check blacklisted IPs
        blacklisted = metrics.get('blacklisted_ips', 0)
        if blacklisted > self.gps_thresholds['blacklist_count_critical']:
            if self.should_alert("gps_blacklist_critical"):
                alerts.append({
                    'severity': 'critical',
                    'title': 'Critical: Many IPs blacklisted',
                    'message': f'{blacklisted} IPs are blacklisted - possible attack',
                    'tags': ['gps_tcp', 'security', 'critical']
                })
        elif blacklisted > self.gps_thresholds['blacklist_count_warning']:
            if self.should_alert("gps_blacklist_warning"):
                alerts.append({
                    'severity': 'warning',
                    'title': 'Warning: IPs being blacklisted',
                    'message': f'{blacklisted} IPs are blacklisted',
                    'tags': ['gps_tcp', 'security', 'warning']
                })
        
        # Check invalid message rate
        total_messages = metrics.get('messages_received', 1)
        invalid_messages = metrics.get('messages_invalid', 0)
        invalid_rate = (invalid_messages / total_messages) * 100 if total_messages > 0 else 0
        
        if invalid_rate > self.gps_thresholds['invalid_message_rate']:
            if self.should_alert("gps_invalid_messages"):
                alerts.append({
                    'severity': 'warning',
                    'title': 'High rate of invalid GPS messages',
                    'message': f'Invalid message rate: {invalid_rate:.1f}%',
                    'tags': ['gps_tcp', 'data_quality']
                })
        
        return alerts
    
    def check_database_alerts(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check database metrics and generate alerts"""
        alerts = []
        
        # Check connection pool
        active_connections = metrics.get('connections_active', 0)
        total_connections = metrics.get('connections_total', 100)
        usage_percent = (active_connections / total_connections) * 100 if total_connections > 0 else 0
        
        if usage_percent > self.database_thresholds['connection_pool_critical']:
            if self.should_alert("db_connections_critical"):
                alerts.append({
                    'severity': 'critical',
                    'title': 'Critical: Database connection pool exhausted',
                    'message': f'Connection pool at {usage_percent:.0f}% ({active_connections}/{total_connections})',
                    'tags': ['database', 'connections', 'critical']
                })
        elif usage_percent > self.database_thresholds['connection_pool_warning']:
            if self.should_alert("db_connections_warning"):
                alerts.append({
                    'severity': 'warning',
                    'title': 'Warning: High database connection usage',
                    'message': f'Connection pool at {usage_percent:.0f}% ({active_connections}/{total_connections})',
                    'tags': ['database', 'connections', 'warning']
                })
        
        # Check replication lag
        replication_lag = metrics.get('replication_lag_seconds', 0)
        if replication_lag > self.database_thresholds['replication_lag_seconds']:
            if self.should_alert("db_replication_lag"):
                alerts.append({
                    'severity': 'warning',
                    'title': 'Database replication lag detected',
                    'message': f'Replication lag: {replication_lag} seconds',
                    'tags': ['database', 'replication']
                })
        
        return alerts
    
    def check_all_metrics(self, platform_metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check all metrics and generate alerts"""
        all_alerts = []
        
        # Check each component
        if 'queues' in platform_metrics:
            queue_alerts = self.check_queue_alerts(platform_metrics['queues'].get('queues', {}))
            all_alerts.extend(queue_alerts)
        
        if 'live_tracking' in platform_metrics:
            live_alerts = self.check_live_tracking_alerts(platform_metrics['live_tracking'])
            all_alerts.extend(live_alerts)
        
        if 'gps_tcp_server' in platform_metrics:
            gps_alerts = self.check_gps_tcp_alerts(platform_metrics['gps_tcp_server'])
            all_alerts.extend(gps_alerts)
        
        if 'database' in platform_metrics:
            db_alerts = self.check_database_alerts(platform_metrics['database'])
            all_alerts.extend(db_alerts)
        
        return all_alerts


# Global alert rules instance
alert_rules = AlertRules()