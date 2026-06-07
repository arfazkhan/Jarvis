"""ArvisX container liveness probe. App is alive if the port answers — a 401
(API key enforced) still proves the server is up, so only a connection failure
is unhealthy. Exit 0 = healthy, 1 = down."""
import os
import sys
import urllib.error
import urllib.request

url = "http://127.0.0.1:%s/api/v1/community/overview" % os.environ.get("ARVISX_API_PORT", "8090")
try:
    urllib.request.urlopen(url, timeout=4)
except urllib.error.HTTPError:
    pass  # 401/4xx — server is up, just guarded
except Exception:
    sys.exit(1)
sys.exit(0)
