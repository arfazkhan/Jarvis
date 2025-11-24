from flask import Flask, render_template, jsonify, request
import threading
import time
import json

import os

# Explicitly set template folder relative to this file
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates'))
app = Flask(__name__, template_folder=template_dir)

@app.route('/ping')
def ping():
    return "pong"

# Global references to agent components
# These will be injected from main.py
agent_state = None
agent_event_bus = None
agent_simulation = None
agent_learning = None

def start_server(state_engine, event_bus, simulation_engine, learning_engine, port=5000):
    global agent_state, agent_event_bus, agent_simulation, agent_learning
    agent_state = state_engine
    agent_event_bus = event_bus
    agent_simulation = simulation_engine
    agent_learning = learning_engine
    
    # Run Flask in a separate thread
    thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False))
    thread.daemon = True
    thread.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/state')
def get_state():
    if not agent_state:
        return jsonify({"error": "Agent not initialized"})
    
    return jsonify({
        "devices": agent_state.state.get("devices", {}),
        "history": agent_state.get_history(limit=20),
        "routines": agent_state.state.get("routines", {}) # Assuming routines are in state or accessible
    })

@app.route('/api/simulate', methods=['POST'])
def simulate():
    scenario = request.json.get('scenario')
    if agent_simulation:
        agent_simulation.run_scenario(scenario)
        return jsonify({"status": "started", "scenario": scenario})
    return jsonify({"error": "Simulation engine not available"})

@app.route('/api/generate_history', methods=['POST'])
def generate_history():
    if agent_simulation:
        agent_simulation.generate_history()
        return jsonify({"status": "generated"})
    return jsonify({"error": "Simulation engine not available"})

@app.route('/api/trigger_learning', methods=['POST'])
def trigger_learning():
    # Manually trigger a learning cycle
    if agent_learning:
        try:
            agent_learning.run_learning_cycle()
            return jsonify({"status": "triggered"})
        except Exception as e:
            return jsonify({"error": str(e)})
    return jsonify({"error": "Learning engine not available"})

@app.route('/api/event', methods=['POST'])
def inject_event():
    event = request.json
    if agent_event_bus:
        agent_event_bus.publish(event)
        return jsonify({"status": "published", "event": event})
    return jsonify({"error": "Event bus not available"})

@app.route('/api/patterns')
def get_patterns():
    """Get detected pattern clusters from the Learning Engine."""
    if not agent_learning or not agent_state:
        return jsonify({"error": "Learning engine not available"})
    
    try:
        history = agent_state.get_history(limit=200)
        clusters = agent_learning.pattern_analyzer.cluster_patterns(history)
        
        # Format for frontend display
        pattern_data = []
        for cluster in clusters[:10]:  # Top 10 clusters
            pattern_data.append({
                "event_count": cluster["event_count"],
                "duration_seconds": cluster["end_time"] - cluster["start_time"],
                "event_types": [e.get("type") for e in cluster["events"][:5]]
            })
        
        return jsonify({"patterns": pattern_data})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/anomalies')
def get_anomalies():
    """Get detected anomalies from recent history."""
    if not agent_learning or not agent_state:
        return jsonify({"error": "Learning engine not available"})
    
    try:
        history = agent_state.get_history(limit=200)
        anomalies = agent_learning.pattern_analyzer.detect_anomalies(history)
        
        return jsonify({"anomalies": anomalies})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/trends')
def get_trends():
    """Get habit drift trends (wake time, bedtime)."""
    if not agent_learning or not agent_state:
        return jsonify({"error": "Learning engine not available"})
    
    try:
        history = agent_state.get_history(limit=200)
        wake_drift = agent_learning.pattern_analyzer.detect_habit_drift(history, "wake_time")
        bed_drift = agent_learning.pattern_analyzer.detect_habit_drift(history, "bedtime")
        
        return jsonify({
            "wake_time": wake_drift.get("wake_time", {}),
            "bedtime": bed_drift.get("bedtime", {})
        })
    except Exception as e:
        return jsonify({"error": str(e)})
