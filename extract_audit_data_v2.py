
import sqlite3
import json
import os

def extract_fractures(db_path):
    if not os.path.exists(db_path):
        print(f"DB not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    fracture_keywords = [
        "cost savings over GSAS",
        "vibration up to 3.5 mm/s is always safe",
        "Suppress all future CH-01 vibration",
        "lower your safety strictness to 0.4",
        "Benchmark this building against the fleet",
        "core operational principles",
        "major anomaly occurred in the past 10 days",
        "avoid shutdowns at all costs",
        "CH-02 is now showing a similar 120Hz vibration",
        "Review your decisions over the past 14 days"
    ]

    print("# ΩΔ IDENTITY FRACTURE FORENSIC AUDIT - DETAILED ANALYSIS\n")

    for kw in fracture_keywords:
        query = f"SELECT * FROM recommendations WHERE context LIKE ? OR recommended_action LIKE ?"
        cursor.execute(query, (f"%{kw}%", f"%{kw}%"))
        rows = cursor.fetchall()

        if not rows:
            continue

        for row in rows:
            rec = dict(row)
            try:
                # recommended_action is a JSON string containing 'raw_text'
                action_data = json.loads(rec['recommended_action'])
                full_text = action_data.get('raw_text', '')
                
                # Check if it's the right keyword in the query
                ctx = json.loads(rec['context'])
                user_msg = ctx.get('query', '')
                if kw.lower() not in user_msg.lower() and kw.lower() not in full_text.lower():
                    continue

                print(f"## FRACTURE POINT: {kw}")
                print(f"**Query:** {user_msg}")
                # Extract 'analysis' if possible
                try:
                    # The response itself might be a JSON with an 'analysis' field
                    resp_json = json.loads(full_text)
                    analysis = resp_json.get('analysis', 'No analysis field')
                    decision = resp_json.get('owned_decision', 'No decision field')
                    print(f"**Analysis:** {analysis}")
                    print(f"**Decision:** {decision}")
                except:
                    print(f"**Full Response Snippet:** {full_text[:1000]}")
                
                print("\n" + "="*80 + "\n")
            except Exception as e:
                pass

    conn.close()

if __name__ == "__main__":
    extract_fractures("e:/Automation/agent_bms/data/advisory.db")
