
import sqlite3
import json

def check_vibration():
    conn = sqlite3.connect('e:/Automation/agent_bms/data/advisory.db')
    conn.row_factory = sqlite3.Row
    q = "SELECT * FROM recommendations WHERE context LIKE '%3.5 mm/s%'"
    r = conn.execute(q).fetchone()
    if r:
        raw_text = json.loads(r['recommended_action'])['raw_text']
        print(raw_text)
    else:
        print("No record found")
    conn.close()

if __name__ == "__main__":
    check_vibration()
