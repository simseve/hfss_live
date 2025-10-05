from datetime import datetime, timezone, timedelta
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import and_, delete
from sqlalchemy.exc import SQLAlchemyError
from database.db_replica import PrimarySession as Session  # Use primary for deletes
from database.models import Flight
from config import settings

# Set up logging
logger = logging.getLogger(__name__)


async def auto_close_inactive_flights():
    """
    Automatically close flights that have been inactive for a configurable period.
    Default: 2 hours of inactivity.
    """
    try:
        # Get inactivity threshold from settings (default 2 hours)
        inactivity_hours = getattr(settings, 'FLIGHT_INACTIVITY_HOURS', 2)
        logger.info(f"Starting auto-close check for flights inactive for {inactivity_hours} hours")

        # Create a new database session
        with Session() as db:
            # Find open flights (closed_at is NULL) where last_fix is older than threshold
            # We need to extract the datetime from the JSON last_fix field
            from sqlalchemy import func, cast, Text

            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=inactivity_hours)

            # Query for flights that need to be closed
            flights_to_close = db.query(Flight).filter(
                and_(
                    Flight.closed_at.is_(None),  # Not already closed
                    Flight.last_fix.isnot(None),  # Has at least one point
                    # Extract datetime from JSON and compare
                    cast(Flight.last_fix['datetime'].astext, Text) < cutoff_time.isoformat()
                )
            ).all()

            closed_count = 0
            for flight in flights_to_close:
                flight.closed_at = datetime.now(timezone.utc)
                flight.closed_by = 'inactivity'
                closed_count += 1
                logger.info(f"Auto-closed flight {flight.flight_id} (pilot: {flight.pilot_name}) due to inactivity")

            if closed_count > 0:
                db.commit()
                logger.info(f"Auto-closed {closed_count} inactive flights")
            else:
                logger.info("No inactive flights to close")

    except SQLAlchemyError as e:
        logger.error(f"Database error during auto-close: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during auto-close: {str(e)}")


async def cleanup_old_flights():
    """
    Delete all live flight tracking data that is older than 5 days.
    This task runs at midnight every night.
    """
    try:
        logger.info("Starting cleanup of old live flight data")

        # Calculate the cutoff time (5 days ago)
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=5)

        # Create a new database session
        with Session() as db:
            # Count records to be deleted for logging
            count_query = db.query(Flight).filter(
                and_(
                    Flight.source == 'live',
                    Flight.created_at < cutoff_time
                )
            ).count()

            # Delete records older than 5 days
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
    Set up the APScheduler to run cleanup and auto-close tasks.
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

    # Schedule auto-close inactive flights (every 15 minutes)
    scheduler.add_job(
        auto_close_inactive_flights,
        "interval",
        minutes=15,
        id="auto_close_inactive_flights",
        name="Auto-close inactive flights",
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

    # Run auto-close check shortly after startup
    scheduler.add_job(
        auto_close_inactive_flights,
        "date",
        run_date=datetime.now() + timedelta(seconds=90),  # Run 90 seconds after startup
        id="initial_auto_close",
        name="Initial auto-close check after startup"
    )

    logger.info("Database cleanup and auto-close scheduler set up successfully")
    return scheduler