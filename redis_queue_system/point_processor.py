"""
Background worker for processing queued points
"""
import asyncio
import logging
import traceback
from typing import List, Dict
from datetime import datetime, timezone
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert
from database.db_replica import PrimarySession as Session  # Use primary for writes
from database.models import LiveTrackPoint, UploadedTrackPoint, ScoringTracks
from geoalchemy2.functions import ST_SetSRID, ST_MakePoint
from redis_queue_system.redis_queue import redis_queue, QUEUE_NAMES

logger = logging.getLogger(__name__)


class PointProcessor:
    def __init__(self):
        self.processing = False
        self.stats = {
            'processed': 0,
            'failed': 0,
            'last_processed': None
        }

    async def start_processing(self):
        """Start the background processing loop"""
        if self.processing:
            logger.warning("Point processor already running")
            return

        self.processing = True
        logger.info("Starting point processor")

        # Start processing tasks for each queue type
        tasks = []
        for queue_type in QUEUE_NAMES.values():
            task = asyncio.create_task(self._process_queue_loop(queue_type))
            tasks.append(task)

        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error in processing loop: {e}")
        finally:
            self.processing = False

    async def stop_processing(self):
        """Stop the background processing"""
        self.processing = False
        logger.info("Stopping point processor")

    async def _process_queue_loop(self, queue_name: str):
        """Main processing loop for a specific queue"""
        logger.info(f"Starting processing loop for {queue_name}")
        cycle_count = 0
        while self.processing:
            try:
                cycle_count += 1
                if cycle_count % 10 == 1:  # Log every 10 cycles
                    logger.debug(f"Processing cycle {cycle_count} for {queue_name}")
                
                # Process batches from this queue
                await self._process_queue_batch(queue_name)

                # Small delay between processing cycles
                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Error processing {queue_name}: {e}, traceback: {traceback.format_exc()}")
                await asyncio.sleep(5)  # Longer delay on error

    async def _process_queue_batch(self, queue_name: str):
        """Process a single batch from the queue"""
        # Get batch of items to process
        # Process up to 10 queue items per cycle
        try:
            items = await redis_queue.dequeue_batch(queue_name, batch_size=10)
        except Exception as e:
            logger.error(f"Failed to dequeue from {queue_name}: {e}")
            return

        if not items:
            return

        logger.info(f"Processing {len(items)} queue items from {queue_name}")

        # Process each queued item independently
        # Each item is already a batch of points (e.g., 100 points per chunk)
        total_processed = 0
        total_failed = 0
        
        for item in items:
            item_points = item.get('points', [])
            if not item_points:
                continue
            
            # Process this chunk
            success = False
            try:
                if queue_name == QUEUE_NAMES['live']:
                    success = await self._process_live_points(item_points)
                elif queue_name == QUEUE_NAMES['upload']:
                    success = await self._process_upload_points(item_points)
                elif queue_name == QUEUE_NAMES['flymaster']:
                    success = await self._process_flymaster_points(item_points)
                elif queue_name == QUEUE_NAMES['scoring']:
                    success = await self._process_scoring_points(item_points)
                
                if success:
                    total_processed += len(item_points)
                    logger.debug(f"Successfully processed chunk with {len(item_points)} points")
                else:
                    total_failed += len(item_points)
                    logger.error(f"Failed to process chunk with {len(item_points)} points")
                    
            except Exception as e:
                total_failed += len(item_points)
                logger.error(f"Error processing chunk: {e}")
                # Continue with next chunk even if one fails
                continue
        
        # Update stats
        if total_processed > 0:
            self.stats['processed'] += total_processed
            logger.info(f"Processed {total_processed} points from {len(items)} chunks")
        if total_failed > 0:
            self.stats['failed'] += total_failed
            logger.warning(f"Failed to process {total_failed} points")
        
        self.stats['last_processed'] = datetime.now(timezone.utc).isoformat()

    async def _process_live_points(self, points: List[Dict]) -> bool:
        """Process live tracking points"""
        try:
            with Session() as db:
                # Use the dictionaries directly for batch insert
                # Batch insert with conflict handling
                stmt = insert(LiveTrackPoint).on_conflict_do_nothing(
                    index_elements=['flight_id', 'lat', 'lon', 'datetime']
                )
                db.execute(stmt, points)
                db.commit()

                logger.info(
                    f"Successfully processed {len(points)} live points")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error processing live points: {e}")
            return False
        except Exception as e:
            logger.error(f"Error processing live points: {e}")
            return False

    async def _process_upload_points(self, points: List[Dict]) -> bool:
        """Process uploaded track points"""
        try:
            with Session() as db:
                # Convert datetime strings back to datetime objects if needed
                processed_points = []
                for point in points:
                    processed_point = point.copy()
                    # Handle datetime conversion
                    if 'datetime' in processed_point and isinstance(processed_point['datetime'], str):
                        from datetime import datetime
                        processed_point['datetime'] = datetime.fromisoformat(
                            processed_point['datetime'].replace('Z', '+00:00')
                        )
                    processed_points.append(processed_point)
                
                # Batch insert with conflict handling
                stmt = insert(UploadedTrackPoint).on_conflict_do_nothing(
                    index_elements=['flight_id', 'lat', 'lon', 'datetime']
                )
                db.execute(stmt, processed_points)
                db.commit()

                logger.info(
                    f"Successfully processed {len(processed_points)} upload points")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error processing upload points: {e}")
            return False
        except Exception as e:
            logger.error(f"Error processing upload points: {e}")
            return False

    async def _process_flymaster_points(self, points: List[Dict]) -> bool:
        """Convert Flymaster device points to live tracking points"""
        try:
            with Session() as db:
                # Group points by device to handle flight creation/detection
                from collections import defaultdict
                points_by_device = defaultdict(list)
                
                for point in points:
                    points_by_device[point['device_id']].append(point)
                
                live_points = []
                
                for device_id, device_points in points_by_device.items():
                    # Sort points by time to ensure proper ordering
                    device_points.sort(key=lambda x: x['date_time'])
                    
                    # Get or create flight for this device
                    flight = self._get_or_create_flymaster_flight(
                        db, device_id, device_points[0]
                    )
                    
                    if not flight:
                        logger.error(f"Failed to get/create flight for device {device_id}")
                        continue
                    
                    # Convert to live tracking points format
                    for point in device_points:
                        # Handle both datetime object and ISO string
                        point_datetime = point['date_time']
                        if isinstance(point_datetime, str):
                            point_datetime = datetime.fromisoformat(point_datetime.replace('Z', '+00:00'))
                        
                        live_point = {
                            'flight_id': flight.flight_id,
                            'flight_uuid': str(flight.id),
                            'datetime': point_datetime,
                            'lat': point['lat'],
                            'lon': point['lon'],
                            'alt': point['gps_alt'],
                            'speed': point.get('speed'),
                            'heading': point.get('heading')
                        }
                        live_points.append(live_point)
                
                # Batch insert as live tracking points
                if live_points:
                    stmt = insert(LiveTrackPoint).on_conflict_do_nothing(
                        index_elements=['flight_id', 'lat', 'lon', 'datetime']
                    )
                    db.execute(stmt, live_points)
                    db.commit()
                    
                    logger.info(
                        f"Successfully converted {len(live_points)} Flymaster points to live tracking")
                
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error processing Flymaster points: {e}")
            return False
        except Exception as e:
            logger.error(f"Error processing Flymaster points: {e}")
            return False
    
    def _get_or_create_flymaster_flight(self, db, device_id: int, first_point: Dict):
        """Get existing flight or create new one for Flymaster device
        
        Uses the same logic as live/upload - race and pilot info comes from device registration.
        Points are only processed if the device is registered with valid race/pilot info.
        """
        from database.models import Flight, Race
        from datetime import datetime, timedelta
        
        try:
            # Get race and pilot info from the point (added by API endpoint from registration)
            race_id = first_point.get('race_id')
            pilot_id = first_point.get('pilot_id')
            pilot_name = first_point.get('pilot_name')
            race_uuid = first_point.get('race_uuid')
            
            # If any required info is missing, device is not properly registered
            if not all([race_id, pilot_id, pilot_name, race_uuid]):
                logger.warning(f"Device {device_id} missing registration info - skipping points")
                return None
            
            # Verify the race exists (should exist from registration)
            race = db.query(Race).filter(Race.race_id == race_id).first()
            if not race:
                logger.error(f"Race {race_id} not found for device {device_id}")
                return None
            
            # Create flight ID using same pattern as live/upload
            # TODO: When end-of-flight signal is implemented, add timestamp suffix
            flight_id = f"flymaster-{pilot_id}-{race_id}-{device_id}"
            
            # Check if we already have this flight
            existing_flight = db.query(Flight).filter(
                Flight.flight_id == flight_id,
                Flight.source == 'flymaster_live'
            ).first()
            
            if existing_flight:
                logger.debug(f"Using existing Flymaster flight: {flight_id}")
                return existing_flight
            
            # Create new flight using registration data (same as live/upload)
            flight = Flight(
                flight_id=flight_id,
                race_uuid=race.id,  # Use race UUID from database
                race_id=race_id,
                pilot_id=pilot_id,
                pilot_name=pilot_name,
                created_at=datetime.now(timezone.utc),
                source='flymaster_live',  # Mark as Flymaster live data
                device_id=str(device_id)
                # first_fix and last_fix will be handled by database triggers
            )
            db.add(flight)
            db.commit()
            db.refresh(flight)
            
            logger.info(f"Created Flymaster flight {flight_id} for {pilot_name} in race {race_id}")
            return flight
            
        except Exception as e:
            logger.error(f"Error managing Flymaster flight: {e}")
            db.rollback()
            return None

    async def _process_scoring_points(self, points: List[Dict]) -> bool:
        """Process scoring track points"""
        try:
            with Session() as db:
                # Batch insert with conflict handling
                stmt = insert(ScoringTracks).on_conflict_do_nothing(
                    index_elements=['flight_uuid', 'date_time', 'lat', 'lon']
                )
                db.execute(stmt, points)
                db.commit()

                logger.info(
                    f"Successfully processed {len(points)} scoring points")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error processing scoring points: {e}")
            return False
        except Exception as e:
            logger.error(f"Error processing scoring points: {e}")
            return False

    def get_stats(self) -> Dict:
        """Get processing statistics"""
        return self.stats.copy()

    async def start(self):
        """Start background processing tasks"""
        if hasattr(self, 'tasks') and self.tasks:
            logger.warning("Point processor already started")
            return

        logger.info("Starting background point processors")
        self.processing = True
        self.tasks = []

        # Start processing tasks for each queue type
        for queue_name in QUEUE_NAMES.values():
            task = asyncio.create_task(self._process_queue_loop(queue_name))
            self.tasks.append(task)

        logger.info(f"Started {len(self.tasks)} background processing tasks")

    async def stop(self):
        """Stop background processing tasks"""
        logger.info("Stopping background point processors")
        self.processing = False

        if hasattr(self, 'tasks') and self.tasks:
            # Cancel all tasks
            for task in self.tasks:
                task.cancel()

            # Wait for tasks to complete cancellation
            try:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Error during task cancellation: {e}")

            self.tasks = []

        logger.info("Background point processors stopped")


# Global processor instance
point_processor = PointProcessor()
