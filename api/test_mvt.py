import requests
import mapbox_vector_tile
import gzip

# Test your MVT endpoint
def test_mvt_endpoint():
    # Replace these values with your actual test data
    z, x, y = 0, 0, 0  # Example tile coordinates
    flight_uuid = "bc52c874-b845-4057-a67f-270c9807ca0d"  # Example UUID
    source = "live"  # Either "live" or "upload"
    gzip_param = False
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY3OTgwNWQ2MTJlNjI5YTg4MzhhNzA2YiIsInJhY2VfaWQiOiI2Nzk4MDU1ODEyZTYyOWE4ODM4YTcwNTkiLCJwaWxvdF9uYW1lIjoiU2ltb25lIFNldmVyaW5pIiwiZXhwIjoxNzcxNTQ1NTk5LCJyYWNlIjp7Im5hbWUiOiJIRlNTIFRyYWNrZXIgTGl2ZSIsImRhdGUiOiIyMDI1LTAyLTE5IiwidGltZXpvbmUiOiJFdXJvcGUvUm9tZSIsImxvY2F0aW9uIjoiVGVzdCIsImVuZF9kYXRlIjoiMjAyNi0wMi0xOSJ9LCJlbmRwb2ludHMiOnsibGl2ZSI6Ii9saXZlIiwidXBsb2FkIjoiL3VwbG9hZCJ9fQ.9jLAcQ-ejTHXZMxCueJNGuBh87oCgPJltT0fPvJuQQE"
    
    # URL to your endpoint with all parameters in query string
    url = f"http://127.0.0.1:8000/tracking/mvt/{z}/{x}/{y}?flight_uuid={flight_uuid}&source={source}&gzip={str(gzip_param).lower()}&token={token}"
    
    # Headers should include 'accept' header as in the curl command
    headers = {
        "accept": "application/json"
    }
    
    # Make the request
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        print(f"Successfully retrieved tile: {response.status_code}")
        
        # Check if response is gzipped
        content_encoding = response.headers.get("Content-Encoding")
        
        if content_encoding == "gzip":
            # Decompress gzipped content
            mvt_data = gzip.decompress(response.content)
        else:
            mvt_data = response.content
            
        # Decode MVT data
        try:
            decoded = mapbox_vector_tile.decode(mvt_data)
            
            # Print out information about the tile
            print(f"Layers in tile: {list(decoded.keys())}")
            
            # Check if our layer exists
            if "track_points" in decoded:
                layer = decoded["track_points"]
                features = layer["features"]
                print(f"Number of points in tile: {len(features)}")
                
                # Print sample of points
                for i, feature in enumerate(features[:3]):
                    print(f"Point {i}:")
                    print(f"  Coordinates: {feature['geometry']['coordinates']}")
                    print(f"  Properties: {feature['properties']}")
                    
                if len(features) > 3:
                    print("...")
                    
            else:
                print("No track_points layer found in tile")
                
        except Exception as e:
            print(f"Error decoding MVT data: {e}")
    else:
        print(f"Error retrieving tile: {response.status_code}")
        print(response.text)

# Run the test
if __name__ == "__main__":
    test_mvt_endpoint()