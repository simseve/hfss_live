import requests
import mapbox_vector_tile
import gzip
import time

# Test your MVT endpoint


def test_mvt_endpoint():
    # Replace these values with your actual test data
    z, x, y = 0, 0, 0  # Example tile coordinates
    flight_uuid = "e3077e36-bc4c-4373-bada-72b8cb183a5e"  # Example UUID
    source = "live"  # Either "live" or "upload"
    gzip_param = False
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY4MGY4NTRmMmI4NTk5ZDZhMzM2ZDUxZiIsInJhY2VfaWQiOiI2Nzk4MDU1ODEyZTYyOWE4ODM4YTcwNTkiLCJwaWxvdF9uYW1lIjoiVml0IFJlbmEiLCJleHAiOjE3NzE1NDU1OTksInJhY2UiOnsibmFtZSI6IkhGU1MgVHJhY2tlciBMaXZlIiwiZGF0ZSI6IjIwMjUtMDItMTkiLCJ0aW1lem9uZSI6IkV1cm9wZS9Sb21lIiwibG9jYXRpb24iOiJUZXN0IiwiZW5kX2RhdGUiOiIyMDI2LTAyLTE5In0sImVuZHBvaW50cyI6eyJsaXZlIjoiL2xpdmUiLCJ1cGxvYWQiOiIvdXBsb2FkIn19.Se_km_mMkESwo6rUjU8GPW4zr6Gr0GvvbGv07ReOhTA"

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
                    print(
                        f"  Coordinates: {feature['geometry']['coordinates']}")
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

# Test PostGIS MVT endpoint


def test_postgis_mvt_endpoint():
    # Replace these values with your actual test data
    z, x, y = 0, 0, 0  # Example tile coordinates
    flight_uuid = "e3077e36-bc4c-4373-bada-72b8cb183a5e"  # Example UUID
    source = "live"  # Either "live" or "upload"
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY4MGY4NTRmMmI4NTk5ZDZhMzM2ZDUxZiIsInJhY2VfaWQiOiI2Nzk4MDU1ODEyZTYyOWE4ODM4YTcwNTkiLCJwaWxvdF9uYW1lIjoiVml0IFJlbmEiLCJleHAiOjE3NzE1NDU1OTksInJhY2UiOnsibmFtZSI6IkhGU1MgVHJhY2tlciBMaXZlIiwiZGF0ZSI6IjIwMjUtMDItMTkiLCJ0aW1lem9uZSI6IkV1cm9wZS9Sb21lIiwibG9jYXRpb24iOiJUZXN0IiwiZW5kX2RhdGUiOiIyMDI2LTAyLTE5In0sImVuZHBvaW50cyI6eyJsaXZlIjoiL2xpdmUiLCJ1cGxvYWQiOiIvdXBsb2FkIn19.Se_km_mMkESwo6rUjU8GPW4zr6Gr0GvvbGv07ReOhTA"

    # URL to your new PostGIS MVT endpoint
    url = f"http://127.0.0.1:8000/tracking/postgis-mvt/{z}/{x}/{y}?flight_uuid={flight_uuid}&source={source}&token={token}"

    # Headers should include 'accept' header as in the curl command
    headers = {
        "accept": "application/json"
    }

    # Make the request
    print("Testing PostGIS MVT endpoint...")
    start_time = time.time()
    response = requests.get(url, headers=headers)
    elapsed_time = time.time() - start_time
    print(f"Request completed in {elapsed_time:.4f} seconds")

    if response.status_code == 200:
        print(f"Successfully retrieved tile: {response.status_code}")

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
                    print(
                        f"  Coordinates: {feature['geometry']['coordinates']}")
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


# Performance comparison test
def performance_comparison(iterations=5, zoom_levels=[0, 5, 10, 15]):
    # Replace these values with your actual test data
    flight_uuid = "bc52c874-b845-4057-a67f-270c9807ca0d"  # Example UUID
    source = "live"  # Either "live" or "upload"
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwaWxvdF9pZCI6IjY3OTgwNWQ2MTJlNjI5YTg4MzhhNzA2YiIsInJhY2VfaWQiOiI2Nzk4MDU1ODEyZTYyOWE4ODM4YTcwNTkiLCJwaWxvdF9uYW1lIjoiU2ltb25lIFNldmVyaW5pIiwiZXhwIjoxNzcxNTQ1NTk5LCJyYWNlIjp7Im5hbWUiOiJIRlNTIFRyYWNrZXIgTGl2ZSIsImRhdGUiOiIyMDI1LTAyLTE5IiwidGltZXpvbmUiOiJFdXJvcGUvUm9tZSIsImxvY2F0aW9uIjoiVGVzdCIsImVuZF9kYXRlIjoiMjAyNi0wMi0xOSJ9LCJlbmRwb2ludHMiOnsibGl2ZSI6Ii9saXZlIiwidXBsb2FkIjoiL3VwbG9hZCJ9fQ.9jLAcQ-ejTHXZMxCueJNGuBh87oCgPJltT0fPvJuQQE"

    headers = {"accept": "application/json"}

    print("\nPERFORMANCE COMPARISON:")
    print("=" * 50)
    print(
        f"Running {iterations} iterations for each zoom level: {zoom_levels}")

    for z in zoom_levels:
        # For each zoom level, use appropriate x,y coordinates
        x = 2**(z-1) if z > 0 else 0
        y = 2**(z-1) if z > 0 else 0

        print(f"\nZoom level {z} (x={x}, y={y}):")

        # Test original endpoint
        original_times = []
        for i in range(iterations):
            url = f"http://127.0.0.1:8000/tracking/mvt/{z}/{x}/{y}?flight_uuid={flight_uuid}&source={source}&gzip=false&token={token}"
            start_time = time.time()
            response = requests.get(url, headers=headers)
            elapsed_time = time.time() - start_time
            original_times.append(elapsed_time)
            print(
                f"  Original MVT: Iteration {i+1}/{iterations}: {elapsed_time:.4f}s (Status: {response.status_code})")

        # Test PostGIS endpoint
        postgis_times = []
        for i in range(iterations):
            url = f"http://127.0.0.1:8000/tracking/postgis-mvt/{z}/{x}/{y}?flight_uuid={flight_uuid}&source={source}&token={token}"
            start_time = time.time()
            response = requests.get(url, headers=headers)
            elapsed_time = time.time() - start_time
            postgis_times.append(elapsed_time)
            print(
                f"  PostGIS MVT: Iteration {i+1}/{iterations}: {elapsed_time:.4f}s (Status: {response.status_code})")

        # Calculate averages
        original_avg = sum(original_times) / iterations
        postgis_avg = sum(postgis_times) / iterations

        # Calculate improvement
        improvement = (original_avg - postgis_avg) / \
            original_avg * 100 if original_avg > 0 else 0

        print(f"  Results for zoom level {z}:")
        print(f"    Original MVT average: {original_avg:.4f}s")
        print(f"    PostGIS MVT average:  {postgis_avg:.4f}s")
        print(f"    Improvement: {improvement:.2f}%")


# Run the tests
if __name__ == "__main__":
    print("Testing original MVT endpoint...")
    test_mvt_endpoint()
    print("\n" + "-"*50 + "\n")
    print("Testing PostGIS MVT endpoint...")
    test_postgis_mvt_endpoint()

    # Run performance comparison if server is running
    try:
        performance_comparison(iterations=3, zoom_levels=[0, 10, 15])
    except Exception as e:
        print(f"\nPerformance comparison failed: {e}")
        print("Make sure the server is running and the endpoints are accessible.")
