import sys
import os
import requests
import json

# Add parent directory to path to import from config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_mvt_endpoint():
    # Test parameters
    host = "http://localhost:8000"
    endpoint = "/api/scoring/postgis-mvt/daily"
    zoom = 0
    x = 0
    y = 0

    # Sample flight UUIDs from our diagnostic script
    flight_uuids = [
        "3d96fa37-37bc-4340-a6a0-6fe3c74279ed",
        "211971e5-7ab5-475f-b763-480ce0533d90"
    ]

    # Create request payload
    payload = {"flight_uuids": flight_uuids}

    # Make request to the endpoint
    url = f"{host}{endpoint}/{zoom}/{x}/{y}"
    print(f"Testing endpoint: {url}")
    print(f"With payload: {json.dumps(payload)}")

    try:
        response = requests.post(url, json=payload)

        # Print response details
        print(f"Response status code: {response.status_code}")
        print(f"Response content type: {response.headers.get('Content-Type')}")
        print(f"Response length: {len(response.content)} bytes")

        # Check if we got MVT data
        is_mvt = response.headers.get(
            'Content-Type') == 'application/x-protobuf'
        has_content = len(response.content) > 0

        if is_mvt and has_content:
            print("SUCCESS: Received MVT tile data")
        else:
            print("FAILURE: Did not receive valid MVT tile")
            if not is_mvt:
                print("  - Response content type is not application/x-protobuf")
            if not has_content:
                print("  - Response has no content (empty tile)")

    except Exception as e:
        print(f"Error during request: {str(e)}")


if __name__ == "__main__":
    test_mvt_endpoint()
