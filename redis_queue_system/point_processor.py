"""
Background worker for processing queued points
"""
import asyncio
import logging
from typing import List, Dict
from datetime import datetime, timezone
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert
from database.db_conf import Session
from database.models import LiveTrackPoint, UploadedTrackPoint, Flymaster, ScoringTracks
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
        while self.processing:
            try:
                # Process batches from this queue
                await self._process_queue_batch(queue_name)

                # Small delay between processing cycles
                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Error processing {queue_name}: {e}")
                await asyncio.sleep(5)  # Longer delay on error

    async def _process_queue_batch(self, queue_name: str):
        """Process a single batch from the queue"""
        # Get batch of items to process
        items = await redis_queue.dequeue_batch(queue_name, batch_size=500)

        if not items:
            return

        logger.info(f"Processing {len(items)} batches from {queue_name}")

        # Flatten all points from all items in this batch
        all_points = []
        for item in items:
            all_points.extend(item.get('points', []))

        if not all_points:
            return

        # Process based on queue type
        success = False
        if queue_name == QUEUE_NAMES['live']:
            success = await self._process_live_points(all_points)
        elif queue_name == QUEUE_NAMES['upload']:
            success = await self._process_upload_points(all_points)
        elif queue_name == QUEUE_NAMES['flymaster']:
            success = await self._process_flymaster_points(all_points)
        elif queue_name == QUEUE_NAMES['scoring']:
            success = await self._process_scoring_points(all_points)

        # Update stats
        if success:
            self.stats['processed'] += len(all_points)
        else:
            self.stats['failed'] += len(all_points)

        self.stats['last_processed'] = datetime.now(timezone.utc).isoformat()

    async def _process_live_points(self, points: List[Dict]) -> bool:
        """Process live tracking points"""
        try:
            with Session() as db:
                # Convert to LiveTrackPoint objects
                track_objects = []
                for point_data in points:
                    track_obj = LiveTrackPoint(**point_data)
                    track_objects.append(track_obj.model_dump())

                # Batch insert with conflict handling
                stmt = insert(LiveTrackPoint).on_conflict_do_nothing(
                    index_elements=['flight_id', 'lat', 'lon', 'datetime']
                )
                db.execute(stmt, track_objects)
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
                # Convert to UploadedTrackPoint objects
                track_objects = []
                for point_data in points:
                    track_obj = UploadedTrackPoint(**point_data)
                    track_objects.append(track_obj.model_dump())

                # Batch insert with conflict handling
                stmt = insert(UploadedTrackPoint).on_conflict_do_nothing(
                    index_elements=['flight_id', 'lat', 'lon', 'datetime']
                )
                db.execute(stmt, track_objects)
                db.commit()

                logger.info(
                    f"Successfully processed {len(points)} upload points")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error processing upload points: {e}")
            return False
        except Exception as e:
            logger.error(f"Error processing upload points: {e}")
            return False

    async def _process_flymaster_points(self, points: List[Dict]) -> bool:
        """Process Flymaster device points"""
        try:
            with Session() as db:
                # Prepare data for batch insert (geometry handled by DB trigger)
                flymaster_data = []
                for point_data in points:
                    flymaster_dict = {
                        'device_id': point_data['device_id'],
                        'date_time': point_data['date_time'],
                        'lat': point_data['lat'],
                        'lon': point_data['lon'],
                        'gps_alt': point_data['gps_alt'],
                        'heading': point_data['heading'],
                        'speed': point_data['speed'],
                        'uploaded_at': point_data.get('uploaded_at')
                        # geom will be automatically generated by DB trigger
                    }
                    flymaster_data.append(flymaster_dict)

                # Batch insert with conflict handling
                stmt = insert(Flymaster).on_conflict_do_nothing(
                    index_elements=['device_id', 'date_time', 'lat', 'lon']
                )
                db.execute(stmt, flymaster_data)
                db.commit()

                logger.info(
                    f"Successfully processed {len(points)} Flymaster points")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error processing Flymaster points: {e}")
            return False
        except Exception as e:
            logger.error(f"Error processing Flymaster points: {e}")
            return False

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
