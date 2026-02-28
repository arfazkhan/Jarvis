import React, { useState, useEffect, useRef } from 'react';
import {
  Brain, Cpu, AlertTriangle, ShieldCheck, Play,
  Settings, Zap, Send, MessageSquare, Building2, Thermometer, Fan,
  FastForward, Timer, History
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import './App.css';

const API_BASE = 'http://localhost:8000/api/v1';

const SCENARIOS = [
  { id: 'default', name: 'Standard Day' },
  { id: 'heatwave', name: 'Heatwave Stress' },
  { id: 'malfunction', name: 'Critical Failure' }
];

const LLM_PROVIDERS = [
  { id: 'k2think', name: 'K2-Think', model: 'MBZUAI-IFM/K2-Think' },
  { id: 'groq', name: 'Groq', model: 'llama-3.3-70b-versatile' },
  { id: 'openai', name: 'OpenAI', model: 'gpt-4o-mini' },
  { id: 'openrouter', name: 'OpenRouter', model: 'meta-llama/llama-3.3-70b-instruct' }
];

function App() {
  const [isConfigured, setIsConfigured] = useState(false);
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [simSpeed, setSimSpeed] = useState(1);
  const [pilotPhase, setPilotPhase] = useState('OBSERVATION');
  const [buildingData, setBuildingData] = useState({
    name: "West Bay Executive Tower",
    location: "Doha, Qatar",
    total_area: "16,500 sqm",
    equipment: [
      { id: 'ch-01', name: 'Chiller 01', type: 'Cooling', status: 'Optimal', manual: false },
      { id: 'ch-02', name: 'Chiller 02', type: 'Cooling', status: 'Warning', manual: false },
      { id: 'p-01', name: 'Condenser Pump 01', type: 'Circulation', status: 'Optimal', manual: false },
      { id: 'f-01', name: 'Fresh Air Fan 01', type: 'Ventilation', status: 'Optimal', manual: false }
    ]
  });

  const [tasks, setTasks] = useState([]);
  const [thoughts, setThoughts] = useState([]);
  const [tools, setTools] = useState([]);
  const [messages, setMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [telemetry, setTelemetry] = useState({
    outdoor_temp: 30,
    energy_intensity: 160,
    active_alarms: 0,
    trust_metric: 0.85,
    day: 1,
    sim_time: "00:00",
    waiting_for_pulse: false
  });
  const [batching, setBatching] = useState(false);

  const thoughtEndRef = useRef(null);
  const chatEndRef = useRef(null);

  useEffect(() => {
    if (!isConfigured) return;
    const eventSource = new EventSource(`${API_BASE}/stream/thoughts`);
    eventSource.addEventListener('task_list', (e) => setTasks(JSON.parse(e.data).tasks || []));
    eventSource.addEventListener('progress', (e) => setThoughts(prev => [...prev, { type: 'progress', content: JSON.parse(e.data).content, timestamp: new Date() }]));
    eventSource.addEventListener('think', (e) => {
      const payload = JSON.parse(e.data);
      setThoughts(prev => [...prev, { type: payload.type || 'thought', content: payload.content, timestamp: new Date() }]);
      if (payload.type === 'briefing') setMessages(prev => [...prev, { role: 'agent', content: payload.content, timestamp: new Date(), type: 'briefing' }]);
    });
    eventSource.addEventListener('sim_status', (e) => {
      const payload = JSON.parse(e.data);
      setTelemetry(payload);
      if (payload.day <= 14) setPilotPhase('OBSERVATION');
      else if (payload.day <= 60) setPilotPhase('ADVISORY');
      else setPilotPhase('CRITICAL');
    });
    eventSource.addEventListener('tool_use', (e) => setTools(prev => [...prev, { ...JSON.parse(e.data), status: 'running', timestamp: new Date() }]));
    eventSource.addEventListener('tool_result', (e) => setTools(prev => prev.map(t => t.step === JSON.parse(e.data).step ? { ...t, status: 'completed' } : t)));
    return () => eventSource.close();
  }, [isConfigured]);

  useEffect(() => { thoughtEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [thoughts]);

  const handleRunCycle = async (days = 0) => {
    setBatching(true);
    // If days > 0, it's a batch day run. If 0, it's a single TURN/PULSE.
    await fetch(`${API_BASE}/sim/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'PULSE',
        target_day: days > 0 ? telemetry.day + days - 1 : null
      })
    });
    setBatching(false);
  };

  const setSpeed = async (speed) => {
    setSimSpeed(speed);
    await fetch(`${API_BASE}/sim/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'SET_SPEED', speed })
    });
  };

  const handleEquipmentOverride = async (eqId, value) => {
    setBuildingData(prev => ({
      ...prev,
      equipment: prev.equipment.map(eq => eq.id === eqId ? { ...eq, manual: value } : eq)
    }));
    await fetch(`${API_BASE}/simulation/equipment/override`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ equipment_id: eqId, value })
    });
  };

  const handleChat = async (e) => {
    e.preventDefault();
    if (!chatInput.trim()) return;
    setMessages(prev => [...prev, { role: 'user', content: chatInput, timestamp: new Date() }]);
    const query = chatInput;
    setChatInput('');
    const resp = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    });
    const data = await resp.json();
    setMessages(prev => [...prev, { role: 'agent', content: data.response, timestamp: new Date() }]);
  };

  if (!isConfigured) return <SetupScreen onComplete={() => setIsConfigured(true)} />;

  return (
    <div className="app-container luxury-theme">
      <header className="hud-header luxury-glass">
        <div className="brand-section">
          <div className="logo-orb"><Brain className="text-orange-500 w-5 h-5" /></div>
          <div>
            <h1 className="arvis-title">ARVIS <span className="glass-font">GOLD</span></h1>
            <div className="pilot-badge">{pilotPhase}</div>
          </div>
        </div>

        <div className="telemetry-deck">
          <TelemetryHex icon={<Thermometer />} label="EXT TEMP" value={`${telemetry.outdoor_temp.toFixed(1)}°C`} color="cyan" />
          <TelemetryHex icon={<Zap />} label="EUI INDEX" value={telemetry.energy_intensity.toFixed(0)} color="orange" />
          <TelemetryHex icon={<ShieldCheck />} label="TRUST" value={`${(telemetry.trust_metric * 100).toFixed(0)}%`} color="green" />
          <div className="pilot-progress-box">
            <div className="flex justify-between text-[7px] font-bold opacity-30 uppercase">
              <span>Maturity Arc</span>
              <span>Day {telemetry.day}</span>
            </div>
            <div className="progress-track">
              <motion.div className="progress-fill" animate={{ width: `${(telemetry.day / 90) * 100}%` }} />
            </div>
          </div>
        </div>

        <div className="control-deck">
          <div className="time-controls luxury-glass-dark">
            <button onClick={() => setSpeed(1)} className={simSpeed === 1 ? 'active' : ''}><Play className="w-3 h-3" /></button>
            <button onClick={() => setSpeed(30)} className={simSpeed === 30 ? 'active' : ''}><FastForward className="w-3 h-3" /></button>
            <div className="time-display"><span className="sim-clock">{telemetry.sim_time}</span></div>
          </div>
          <button
            onClick={() => handleRunCycle(0)}
            className={`run-cycle-btn ${telemetry.waiting_for_pulse ? 'pulse-ready' : ''}`}
            disabled={batching}
          >
            {batching ? <Timer className="w-3 h-3 animate-spin" /> : (telemetry.waiting_for_pulse ? <Zap className="w-3 h-3 text-orange-400" /> : <Play className="w-3 h-3" />)}
            <span>{telemetry.waiting_for_pulse ? 'Authorize Pulse' : 'Step Hour'}</span>
          </button>
          <Settings onClick={() => setShowConfigModal(true)} className="w-4 h-4 opacity-30 cursor-pointer" />
        </div>
      </header>

      <div className="content-grid">
        <aside className="left-panel luxury-glass">
          <div className="section-header">
            <Building2 className="w-4 h-4 text-orange-400" />
            <span>Facility Intel</span>
          </div>
          <div className="p-5 flex-1 flex flex-col">
            <div className="mb-6">
              <h3 className="text-xs font-black uppercase tracking-widest">{buildingData.name}</h3>
              <p className="text-[8px] opacity-30 uppercase tracking-tighter">{buildingData.location}</p>
            </div>
            <div className="flex-1">
              <span className="mini-label">Manual Overrides</span>
              {buildingData.equipment.map(eq => (
                <div key={eq.id} className="asset-override-card">
                  {/* Truncated name handled by CSS */}
                  <span>{eq.name}</span>
                  <label className="toggle-switch">
                    <input type="checkbox" checked={eq.manual} onChange={(e) => handleEquipmentOverride(eq.id, e.target.checked)} />
                    <span className="slider"></span>
                  </label>
                </div>
              ))}
            </div>
            <div className="pt-6 border-t border-white/5">
              <span className="mini-label">Scenario Stress</span>
              <div className="grid grid-cols-1 gap-2">
                {SCENARIOS.map(s => (
                  <button key={s.id} className="scenario-btn text-[9px] uppercase font-bold tracking-widest py-2" onClick={() => fetch(`${API_BASE}/sim/scenario`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenario_id: s.id }) })}>
                    {s.name}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </aside>

        <main className="center-panel">
          <section className="cognitive-tower luxury-glass">
            <div className="section-header">
              <Brain className="w-4 h-4 text-orange-400" />
              <span>Cognitive Stream</span>
            </div>
            <div className="thought-stream-premium">
              {/* Only show last 5 thoughts to prevent flooding */}
              {thoughts.slice(-5).map((t, i) => (
                <div key={i} className={`luxury-thought-card ${t.type}`}>
                  <div className="thought-meta">{t.timestamp.toLocaleTimeString()}</div>
                  <p className="text-xs leading-relaxed">{t.content}</p>
                </div>
              ))}
              <div ref={thoughtEndRef} />
            </div>
          </section>

          <footer className="command-input-panel luxury-glass">
            <div className="chat-messages">
              {messages.map((m, i) => (
                <div key={i} className={`luxury-bubble ${m.role} ${m.type || ''}`}>
                  <div className="bubble-header">{m.role === 'agent' ? 'ARVIS' : 'OPERATOR'}</div>
                  <p className="text-xs">{m.content}</p>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>
            <form onSubmit={handleChat} className="command-bar flex">
              <input className="flex-1" placeholder="Enter directive..." value={chatInput} onChange={(e) => setChatInput(e.target.value)} />
              <button type="submit" className="p-4 opacity-40"><Send className="w-4 h-4" /></button>
            </form>
          </footer>
        </main>

        <aside className="right-panel luxury-glass">
          <div className="section-header">
            <Cpu className="w-4 h-4 text-cyan-400" />
            <span>Operational Trace</span>
          </div>
          <div className="tasks-trace-container">
            <div>
              <span className="mini-label">Objectives</span>
              {tasks.map(t => (
                <div key={t.id} className={`mini-task-item ${t.status}`}>
                  <div className={`status-icon ${t.status}`}></div>
                  <span>{t.task}</span>
                </div>
              ))}
            </div>
            <div>
              <span className="mini-label">Briefing History</span>
              <div className="briefing-stack">
                {messages.filter(m => m.type === 'briefing').reverse().slice(0, 3).map((b, i) => (
                  <div key={i} className="brief-history-item py-2 opacity-60">
                    <p className="text-[10px] line-clamp-2 italic">{b.content}</p>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <span className="mini-label">Neural Tools</span>
              <div className="flex flex-wrap gap-2">
                {tools.slice(-4).map((t, i) => <div key={i} className={`tool-chip ${t.status}`}><span>{t.tool}</span></div>)}
              </div>
            </div>
          </div>
        </aside>
      </div>
      <AnimatePresence>
        {showConfigModal && <BuildingConfigModal data={buildingData} onClose={() => setShowConfigModal(false)} onSave={setBuildingData} />}
      </AnimatePresence>
    </div>
  );
}

function BuildingConfigModal({ data, onClose, onSave }) {
  const [local, setLocal] = useState(data);
  return (
    <div className="modal-backdrop">
      <div className="modal-content luxury-glass scale-90">
        <h2 className="text-xl font-black mb-6">Asset Registry</h2>
        <input className="w-full bg-white/5 border-none p-4 rounded-xl mb-6" value={local.name} onChange={e => setLocal({ ...local, name: e.target.value })} />
        <div className="asset-list space-y-2 max-h-60 overflow-y-auto pr-2">
          {local.equipment.map(eq => (
            <div key={eq.id} className="flex justify-between items-center p-3 bg-white/5 rounded-lg">
              <span className="text-sm">{eq.name}</span>
              <span className="text-[10px] opacity-20 uppercase font-black">{eq.type}</span>
            </div>
          ))}
        </div>
        <div className="flex gap-4 mt-10">
          <button className="flex-1 py-4 opacity-40" onClick={onClose}>Cancel</button>
          <button className="flex-1 py-4 bg-orange-500 rounded-xl font-bold" onClick={() => { onSave(local); onClose(); }}>Save</button>
        </div>
      </div>
    </div>
  );
}

function SetupScreen({ onComplete }) {
  const [provider, setProvider] = useState('k2think');
  const [apiKey, setApiKey] = useState('');
  const [loading, setLoading] = useState(false);
  const handleDeploy = async () => {
    setLoading(true);
    const resp = await fetch(`${API_BASE}/config/setup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model: LLM_PROVIDERS.find(p => p.id === provider).model, api_key: apiKey })
    });
    if (resp.ok) onComplete();
    setLoading(false);
  };
  return (
    <div className="setup-container">
      <div className="setup-card luxury-glass">
        <Brain className="w-12 h-12 text-orange-500 mb-6 mx-auto" />
        <h2 className="text-xl font-black tracking-widest mb-10">INITIALIZE ARVIS</h2>
        <div className="grid grid-cols-2 gap-2 mb-8">
          {LLM_PROVIDERS.map(p => (
            <button key={p.id} className={`p-4 rounded-xl text-[10px] font-bold ${provider === p.id ? 'bg-orange-500' : 'bg-white/5 opacity-40'}`} onClick={() => setProvider(p.id)}>{p.name}</button>
          ))}
        </div>
        <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="API ACCESS TOKEN" className="w-full bg-white/5 p-4 rounded-xl mb-6 text-center" />
        <button onClick={handleDeploy} disabled={loading || !apiKey} className="w-full py-4 bg-orange-500 rounded-xl font-black uppercase tracking-widest">{loading ? 'Synthesizing...' : 'Initialize'}</button>
      </div>
    </div>
  );
}

function TelemetryHex({ icon, label, value, color }) {
  return (
    <div className={`tele-box ${color}`}>
      <div className="tele-icon text-white/20">{icon}</div>
      <div>
        <span className="tele-label">{label}</span>
        <span className="tele-value">{value}</span>
      </div>
    </div>
  );
}

export default App;
