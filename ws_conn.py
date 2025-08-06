from fastapi import WebSocket
from starlette.websockets import WebSocketState
from typing import Dict, Set, List, Optional


class ConnectionManager:
    def __init__(self):
        # Active connections by race_id
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # Track which races each user is subscribed to
        self.user_subscriptions: Dict[str, Set[str]] = {}
        # Dictionary to track pilots that have already received their initial data
        # Structure: {race_id: {pilot_id: last_update_time}}
        self.pilots_with_sent_data: Dict[str, Dict[str, float]] = {}
        # Track active XContest flights per race
        # Structure: {race_id: {xc_flight_id: {lastFixTime: str, ...}}}
        self.xc_flights_tracking: Dict[str, Dict[str, Dict]] = {}
        # Store valid HFSS API tokens per race for background updates
        # Structure: {race_id: token}
        self.hfss_tokens: Dict[str, str] = {}

    async def connect(self, websocket: WebSocket, race_id: str, client_id: str):
        """Connect a client to a specific race's updates"""
        await websocket.accept()

        # Initialize race_id list if needed
        if race_id not in self.active_connections:
            self.active_connections[race_id] = set()

        # Add this connection to the race
        self.active_connections[race_id].add(websocket)

        # Track this user's subscriptions
        if client_id not in self.user_subscriptions:
            self.user_subscriptions[client_id] = set()

        self.user_subscriptions[client_id].add(race_id)

        # Send confirmation to the client
        await websocket.send_json({
            "type": "connection_status",
            "status": "connected",
            "race_id": race_id,
            "active_viewers": len(self.active_connections[race_id])
        })

    async def disconnect(self, websocket: WebSocket, client_id: str):
        """Disconnect a client from all subscribed races"""
        # Remove this connection from all races
        for race_id in list(self.active_connections.keys()):
            if websocket in self.active_connections[race_id]:
                self.active_connections[race_id].remove(websocket)

                # Clean up empty race connections
                if len(self.active_connections[race_id]) == 0:
                    del self.active_connections[race_id]
                    self.remove_race_tracking_data(race_id)

        # Clean up user subscriptions
        if client_id in self.user_subscriptions:
            del self.user_subscriptions[client_id]

    async def broadcast_to_race(self, race_id: str, message: dict):
        """Send message to all clients connected to a specific race"""
        if race_id not in self.active_connections:
            return

        inactive_connections = set()

        for connection in self.active_connections[race_id]:
            try:
                if connection.client_state == WebSocketState.CONNECTED:
                    await connection.send_json(message)
            except RuntimeError:
                # Connection is no longer valid
                inactive_connections.add(connection)

        # Clean up any dead connections
        for inactive in inactive_connections:
            if race_id in self.active_connections and inactive in self.active_connections[race_id]:
                self.active_connections[race_id].remove(inactive)

    async def send_command_notification(self, race_id: str, message: dict):
        """Send a command center notification to all clients in a race"""
        await self.broadcast_to_race(race_id, {
            "type": "command_notification",
            "data": message
        })

    async def send_update(self, race_id: str, flights_data: List[dict]):
        """Send tracking updates to all clients in a race"""
        await self.broadcast_to_race(race_id, {
            "type": "track_update",
            "race_id": race_id,
            "flights": flights_data
        })

    def get_active_viewers(self, race_id: str) -> int:
        """Return count of active viewers for a race"""
        if race_id not in self.active_connections:
            return 0
        return len(self.active_connections[race_id])

    def get_pilots_with_sent_data(self, race_id: str) -> Dict[str, float]:
        """Get the set of pilots that have already received their initial data for a race"""
        if race_id not in self.pilots_with_sent_data:
            self.pilots_with_sent_data[race_id] = {}
        return self.pilots_with_sent_data[race_id]

    def add_pilot_with_sent_data(self, race_id: str, pilot_id: str, update_time: float):
        """Record that a pilot has received their data up to update_time"""
        if race_id not in self.pilots_with_sent_data:
            self.pilots_with_sent_data[race_id] = {}
        self.pilots_with_sent_data[race_id][pilot_id] = update_time

    def get_last_update_time(self, race_id: str, pilot_id: str) -> float:
        """Get the last time data was sent for a specific pilot in a race"""
        if race_id in self.pilots_with_sent_data and pilot_id in self.pilots_with_sent_data[race_id]:
            return self.pilots_with_sent_data[race_id][pilot_id]
        return None

    def remove_race_tracking_data(self, race_id: str):
        """Remove tracking data for a race when it's no longer active"""
        if race_id in self.pilots_with_sent_data:
            del self.pilots_with_sent_data[race_id]
        if race_id in self.xc_flights_tracking:
            del self.xc_flights_tracking[race_id]
        if race_id in self.hfss_tokens:
            del self.hfss_tokens[race_id]
    
    def get_xc_flights_tracking(self, race_id: str) -> Dict[str, Dict]:
        """Get XContest flight tracking data for a race"""
        if race_id not in self.xc_flights_tracking:
            self.xc_flights_tracking[race_id] = {}
        return self.xc_flights_tracking[race_id]
    
    def update_xc_flight_tracking(self, race_id: str, flight_id: str, last_fix_time: str, 
                                   pilot_id: str = None, pilot_name: str = None):
        """Update the tracking info for an XContest flight"""
        if race_id not in self.xc_flights_tracking:
            self.xc_flights_tracking[race_id] = {}
        if flight_id not in self.xc_flights_tracking[race_id]:
            self.xc_flights_tracking[race_id][flight_id] = {}
        
        self.xc_flights_tracking[race_id][flight_id]['lastFixTime'] = last_fix_time
        
        # Store pilot info if provided (typically on first tracking)
        if pilot_id:
            self.xc_flights_tracking[race_id][flight_id]['pilot_id'] = pilot_id
        if pilot_name:
            self.xc_flights_tracking[race_id][flight_id]['pilot_name'] = pilot_name
    
    def store_hfss_token(self, race_id: str, token: str):
        """Store a valid HFSS API token for a race"""
        self.hfss_tokens[race_id] = token
    
    def get_hfss_token(self, race_id: str) -> Optional[str]:
        """Get the stored HFSS API token for a race"""
        return self.hfss_tokens.get(race_id)


# Create a global connection manager for the application
manager = ConnectionManager()
