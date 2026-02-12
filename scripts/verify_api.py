import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from api.main import app

def test_api_loading():
    print("🚀 Verifying API Loading...")
    try:
        client = TestClient(app)
        response = client.get("/")
        print(f"✅ Root Endpoint: {response.status_code} {response.json()}")
        
        # Test Docs
        docs = client.get("/docs")
        if docs.status_code == 200:
             print("✅ OpenAPI Docs Generated Successfully")
        else:
             print(f"❌ Docs Failed: {docs.status_code}")

        # Count Routes
        route_count = len(app.routes)
        print(f"✅ Active Routes: {route_count}")
        
    except Exception as e:
        print(f"❌ API Verification Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_api_loading()
