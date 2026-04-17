from api.main import app
import os

print(f"Checking routes for ARVIS mode: {os.getenv('ARVIS_VERTICAL', 'RESIDENTIAL')}")

for route in app.routes:
    if hasattr(route, 'path'):
        print(f"Path: {route.path} | Tags: {getattr(route, 'tags', [])}")
