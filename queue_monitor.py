#!/usr/bin/env python3
"""
Queue monitoring script with alerting capabilities
Can be run as a cron job or systemd service
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict
import aiohttp
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class QueueMonitor:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.thresholds = {
            'pending_items_warning': 1000,
            'pending_items_critical': 5000,
            'dlq_items_warning': 10,
            'dlq_items_critical': 100,
            'processing_lag_seconds': 300  # 5 minutes
        }
        
    async def check_health(self) -> Dict:
        """Check queue health status"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.base_url}/admin/queue/health") as response:
                    return await response.json()
            except Exception as e:
                logger.error(f"Failed to check queue health: {e}")
                return None
    
    async def check_and_alert(self):
        """Check queue health and send alerts if needed"""
        health = await self.check_health()
        
        if not health:
            await self.send_alert("critical", "Queue health check failed - API unreachable")
            return
        
        alerts = []
        
        # Check each queue
        for queue_type, queue_data in health.get('queues', {}).items():
            total_pending = queue_data.get('total_pending', 0)
            dlq_size = queue_data.get('dlq_size', 0)
            
            # Check pending items
            if total_pending > self.thresholds['pending_items_critical']:
                alerts.append({
                    'level': 'critical',
                    'queue': queue_type,
                    'message': f"Critical: {total_pending} items pending in {queue_type}"
                })
            elif total_pending > self.thresholds['pending_items_warning']:
                alerts.append({
                    'level': 'warning',
                    'queue': queue_type,
                    'message': f"Warning: {total_pending} items pending in {queue_type}"
                })
            
            # Check DLQ
            if dlq_size > self.thresholds['dlq_items_critical']:
                alerts.append({
                    'level': 'critical',
                    'queue': queue_type,
                    'message': f"Critical: {dlq_size} items in DLQ for {queue_type}"
                })
            elif dlq_size > self.thresholds['dlq_items_warning']:
                alerts.append({
                    'level': 'warning',
                    'queue': queue_type,
                    'message': f"Warning: {dlq_size} items in DLQ for {queue_type}"
                })
        
        # Send alerts
        for alert in alerts:
            await self.send_alert(alert['level'], alert['message'])
            
        # Log status
        if alerts:
            logger.warning(f"Found {len(alerts)} queue issues")
        else:
            logger.info("All queues healthy")
            
        return alerts
    
    async def auto_recovery(self):
        """Attempt automatic recovery for stuck queues"""
        health = await self.check_health()
        
        if not health:
            return
        
        recovery_actions = []
        
        for queue_type, queue_data in health.get('queues', {}).items():
            dlq_size = queue_data.get('dlq_size', 0)
            
            # Auto-process DLQ if items are present
            if dlq_size > 0 and dlq_size < 100:  # Only auto-process small DLQs
                logger.info(f"Auto-processing {dlq_size} items from {queue_type} DLQ")
                
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.post(
                            f"{self.base_url}/admin/queue/process-dlq/{queue_type}",
                            params={'dry_run': False}
                        ) as response:
                            result = await response.json()
                            recovery_actions.append({
                                'queue': queue_type,
                                'action': 'process_dlq',
                                'result': result
                            })
                    except Exception as e:
                        logger.error(f"Failed to process DLQ for {queue_type}: {e}")
        
        return recovery_actions
    
    async def cleanup_old_items(self, max_age_hours: int = 24):
        """Clean up old items from queues"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.base_url}/admin/queue/cleanup",
                    params={'max_age_hours': max_age_hours, 'dry_run': False}
                ) as response:
                    result = await response.json()
                    logger.info(f"Cleanup result: {result}")
                    return result
            except Exception as e:
                logger.error(f"Failed to cleanup old items: {e}")
                return None
    
    async def send_alert(self, level: str, message: str):
        """
        Send alert via webhook, email, or logging
        Configure based on your infrastructure
        """
        alert = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': level,
            'message': message,
            'source': 'queue_monitor'
        }
        
        # For now, just log the alert
        if level == 'critical':
            logger.critical(f"ALERT: {message}")
        else:
            logger.warning(f"ALERT: {message}")
        
        # TODO: Implement actual alerting (webhook, email, etc.)
        # Example webhook implementation:
        # async with aiohttp.ClientSession() as session:
        #     await session.post(webhook_url, json=alert)
        
        return alert
    
    async def run_monitoring_cycle(self):
        """Run a complete monitoring cycle"""
        logger.info("Starting monitoring cycle")
        
        # Check health and alert
        alerts = await self.check_and_alert()
        
        # Attempt auto-recovery if needed
        if alerts:
            recovery_actions = await self.auto_recovery()
            if recovery_actions:
                logger.info(f"Performed {len(recovery_actions)} recovery actions")
        
        # Clean up old items (run less frequently)
        if datetime.now().hour == 2:  # Run at 2 AM
            await self.cleanup_old_items(24)
        
        logger.info("Monitoring cycle complete")


async def main():
    """Main monitoring loop"""
    monitor = QueueMonitor()
    
    # Run once
    if '--once' in sys.argv:
        await monitor.run_monitoring_cycle()
        return
    
    # Continuous monitoring
    while True:
        try:
            await monitor.run_monitoring_cycle()
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}")
        
        # Wait before next check (5 minutes)
        await asyncio.sleep(300)


if __name__ == "__main__":
    import sys
    asyncio.run(main())