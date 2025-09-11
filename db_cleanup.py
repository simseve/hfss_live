from datetime import datetime, timezone, timedelta
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import and_, delete
from sqlalchemy.exc import SQLAlchemyError
from database.db_replica import PrimarySession as Session  # Use primary for deletes
from database.models import Flight

# Set up logging
logger = logging.getLogger(__name__)


async def cleanup_old_flights():
    """
    Delete all live flight tracking data that is older than 48 hours.
    This task runs at midnight every night.
    """
    try:
        logger.info("Starting cleanup of old live flight data")

        # Calculate the cutoff time (48 hours ago)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=48)

        # Create a new database session
        with Session() as db:
            # Count records to be deleted for logging
            count_query = db.query(Flight).filter(
                and_(
                    Flight.source == 'live',
                    Flight.created_at < cutoff_time
                )
            ).count()

            # Delete records older than 48 hours
            delete_stmt = delete(Flight).where(
                and_(
                    Flight.source == 'live',
                    Flight.created_at < cutoff_time
                )
            )

            result = db.execute(delete_stmt)
            db.commit()

            logger.info(f"Deleted {count_query} old live flight records")

    except SQLAlchemyError as e:
        logger.error(f"Database error during flight cleanup: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during flight cleanup: {str(e)}")


def setup_scheduler():
    """
    Set up the APScheduler to run the cleanup task at midnight every day.
    Returns the scheduler object.
    """
    scheduler = AsyncIOScheduler()

    # Schedule the cleanup task to run at midnight every day
    scheduler.add_job(
        cleanup_old_flights,
        CronTrigger(hour=0, minute=0),  # Run at 00:00 (midnight)
        id="cleanup_old_flights",
        name="Delete old live flight data",
        replace_existing=True
    )

    # Add a job to run immediately after startup to catch up on cleanups if needed
    scheduler.add_job(
        cleanup_old_flights,
        "date",
        run_date=datetime.now() + timedelta(seconds=60),  # Run 60 seconds after startup
        id="initial_cleanup",
        name="Initial cleanup after startup"
    )

    logger.info("Database cleanup scheduler set up successfully")
    return scheduler