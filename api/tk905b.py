"""
TK905B GPS Tracker endpoint
Accepts and logs any JSON data to learn the device's actual format
"""
from fastapi import APIRouter, Request, Response
from typing import Any, Dict
import logging
import json
from datetime import datetime, timezone

# Configure logging with more detail
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/tk905b/data")
async def receive_tk905b_data(request: Request):
    """
    Accept any data from TK905B tracker and log it for analysis.
    This endpoint accepts any JSON format to help us learn what the device sends.
    """
    try:
        # Get raw body
        body = await request.body()
        logger.info("=" * 60)
        logger.info("TK905B RAW DATA RECEIVED")
        logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
        logger.info(f"Content-Type: {request.headers.get('content-type', 'not specified')}")
        logger.info(f"Content-Length: {len(body)} bytes")
        
        # Try to parse as JSON
        try:
            json_data = await request.json()
            logger.info("Successfully parsed as JSON:")
            logger.info(json.dumps(json_data, indent=2))
            
            # Log specific fields if they exist (common GPS tracker fields)
            if isinstance(json_data, dict):
                logger.info("\nExtracted fields:")
                fields_to_check = [
                    'imei', 'IMEI', 'deviceId', 'device_id',
                    'lat', 'latitude', 'LAT', 'Latitude',
                    'lon', 'lng', 'longitude', 'LON', 'Longitude', 
                    'speed', 'Speed', 'SPEED',
                    'altitude', 'alt', 'Alt', 'Altitude',
                    'time', 'timestamp', 'datetime', 'gps_time',
                    'battery', 'bat', 'Battery',
                    'signal', 'gsm', 'Signal',
                    'satellites', 'sat', 'Satellites',
                    'heading', 'bearing', 'direction', 'course',
                    'accuracy', 'hdop', 'acc'
                ]
                
                for field in fields_to_check:
                    if field in json_data:
                        logger.info(f"  {field}: {json_data[field]}")
                
                # Also check for nested structures
                if 'position' in json_data:
                    logger.info(f"  position: {json_data['position']}")
                if 'device' in json_data:
                    logger.info(f"  device: {json_data['device']}")
                    
        except json.JSONDecodeError:
            # Not JSON, log as raw text
            logger.info("Could not parse as JSON, raw body:")
            logger.info(body.decode('utf-8', errors='replace'))
        
        logger.info("=" * 60)
        
        # Always return success so the device keeps sending data
        return {"status": "ok", "message": "Data received and logged"}
        
    except Exception as e:
        logger.error(f"Error processing TK905B data: {e}")
        logger.error(f"Raw body: {body.decode('utf-8', errors='replace') if 'body' in locals() else 'No body'}")
        # Still return success to keep device sending
        return {"status": "ok", "message": "Data received with errors"}


@router.get("/tk905b/data")
async def tk905b_info():
    """
    Information endpoint about TK905B data format
    """
    return {
        "endpoint": "/tracking/tk905b/data",
        "method": "POST",
        "description": "Accepts any JSON data from TK905B GPS tracker",
        "purpose": "Learning endpoint to discover the actual data format",
        "note": "Check logs to see what data format your device sends",
        "common_fields": [
            "imei", "latitude", "longitude", "speed", "altitude",
            "timestamp", "battery", "satellites", "heading"
        ]
    }


# Also accept data at root tk905b endpoint
@router.post("/tk905b")
async def receive_tk905b_root(request: Request):
    """
    Alternative endpoint at /tracking/tk905b (without /data)
    Some devices might be configured to post to the root path
    """
    logger.info("TK905B data received at ROOT endpoint (/tk905b)")
    return await receive_tk905b_data(request)


# Accept GET requests too (some trackers use GET with query params)
@router.get("/tk905b/report")
async def receive_tk905b_get(request: Request):
    """
    Some GPS trackers send data via GET with query parameters
    """
    logger.info("=" * 60)
    logger.info("TK905B GET REQUEST RECEIVED")
    logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    logger.info(f"Query params: {dict(request.query_params)}")
    logger.info("=" * 60)
    
    return {"status": "ok", "message": "GET data received and logged"}