import { useRef, useEffect } from 'react';
import Layout from './components/Layout';
import { useDarkMode } from './hooks/useDarkMode';
import { useArvisStream, type LogEntry } from './hooks/useArvisStream';
import { Activity, Cpu, Zap, Thermometer, BrainCircuit, ShieldAlert, Code2, Rss } from 'lucide-react';

function LogViewer({ logs }: { logs: LogEntry[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <div className="flex-1 overflow-y-auto space-y-4 font-mono text-sm pr-2 custom-scrollbar pb-4">
      {logs.map((log) => {
        if (log.type === 'EVENT') {
          return (
            <div key={log.id} className="p-4 rounded-xl bg-black/5 dark:bg-white/5 border border-black/5 dark:border-white/5 hover:border-black/10 dark:hover:border-white/10 transition-colors animate-fade-in">
              <div className="flex justify-between items-center mb-3">
                <span className="text-xs font-bold text-cta uppercase tracking-wider flex items-center gap-1.5"><ShieldAlert className="w-4 h-4" /> Observation</span>
                <span className="text-xs opacity-50 font-medium">{log.timestamp}</span>
              </div>
              <div className="opacity-90 leading-relaxed text-[13px]">{log.content}</div>
            </div>
          );
        }

        if (log.type === 'REASONING') {
          return (
            <div key={log.id} className="p-4 rounded-xl bg-primary/5 border border-primary/20 hover:border-primary/30 transition-colors animate-fade-in">
              <div className="flex justify-between items-center mb-3">
                <span className="text-xs font-bold text-secondary uppercase tracking-wider flex items-center gap-1.5"><BrainCircuit className="w-4 h-4" /> Internal Thought</span>
                <span className="text-xs opacity-50 font-medium">{log.timestamp}</span>
              </div>
              <div className="text-[13px] opacity-80 whitespace-pre-wrap pl-3 border-l-2 border-primary/40 leading-relaxed font-mono">
                {log.content.replace('<think>', '').replace('</think>', '').trim()}
              </div>
            </div>
          );
        }

        if (log.type === 'TOOL_CALL') {
          return (
            <div key={log.id} className="p-4 rounded-xl bg-cta/5 border border-cta/20 hover:border-cta/30 transition-colors animate-fade-in">
              <div className="flex justify-between items-center mb-2">
                <span className="text-xs font-bold text-cta uppercase tracking-wider flex items-center gap-1.5"><Code2 className="w-4 h-4" /> System Action</span>
                <span className="text-xs opacity-50 font-medium">{log.timestamp}</span>
              </div>
              <code className="text-[13px] text-cta block mt-2 p-2 bg-black/5 dark:bg-black/20 rounded-lg border border-cta/10">
                {log.content}
              </code>
            </div>
          );
        }

        return (
          <div key={log.id} className="p-4 rounded-xl border border-black/5 dark:border-white/10 opacity-70 hover:opacity-100 transition-opacity animate-fade-in">
            <div className="flex justify-between items-center mb-2">
              <span className="text-xs font-bold uppercase tracking-wider">{log.type}</span>
              <span className="text-xs opacity-50 font-medium">{log.timestamp}</span>
            </div>
            <div className="text-[13px] whitespace-pre-wrap">{log.content}</div>
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}

function App() {
  const { isDark, toggle } = useDarkMode();
  const { logs, metrics, connected } = useArvisStream(true);

  return (
    <Layout isDark={isDark} toggleDark={toggle}>
      {/* 70% Business Dashboard */}
      <div className="w-[70%] h-full flex flex-col gap-6">
        <div className="glass-panel rounded-3xl p-8 flex-1 flex flex-col shadow-xl border border-white/20 dark:border-white/5 relative overflow-hidden">

          <div className="flex justify-between items-center mb-8">
            <h2 className="text-2xl font-bold flex items-center gap-3"><Activity className="text-secondary w-7 h-7" /> System Overview</h2>
            <div className={`px-4 py-1.5 rounded-full text-sm font-semibold border flex items-center gap-2 ${connected ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20' : 'bg-red-500/10 text-red-600 border-red-500/20'}`}>
              <div className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`} />
              {connected ? 'Live Data Stream' : 'Disconnected'}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-6 mb-8">
            <div className="p-6 rounded-2xl border border-black/5 dark:border-white/5 bg-white/50 dark:bg-black/20 hover:bg-white/60 dark:hover:bg-black/30 transition-colors cursor-default">
              <div className="text-sm font-medium opacity-70 mb-2 flex items-center gap-2"><ShieldAlert className="w-4 h-4 text-cta" /> Active Alarms</div>
              <div className="text-5xl font-bold text-slate-800 dark:text-white">{metrics.alarms}</div>
            </div>
            <div className="p-6 rounded-2xl border border-black/5 dark:border-white/5 bg-white/50 dark:bg-black/20 hover:bg-white/60 dark:hover:bg-black/30 transition-colors cursor-default">
              <div className="text-sm font-medium opacity-70 mb-2 flex items-center gap-2"><Zap className="w-4 h-4 text-emerald-500" /> Energy Efficiency</div>
              <div className="text-5xl font-bold text-emerald-500">{metrics.efficiency.toFixed(1)}%</div>
            </div>
            <div className="p-6 rounded-2xl border border-black/5 dark:border-white/5 bg-white/50 dark:bg-black/20 hover:bg-white/60 dark:hover:bg-black/30 transition-colors cursor-default">
              <div className="text-sm font-medium opacity-70 mb-2 flex items-center gap-2"><Thermometer className="w-4 h-4 text-primary" /> Building Load</div>
              <div className="text-5xl font-bold text-primary">{metrics.load}</div>
            </div>
          </div>

          <div className="flex-1 rounded-2xl border border-black/5 dark:border-white/5 bg-white/30 dark:bg-black/10 flex items-center justify-center relative overflow-hidden group hover:border-primary/20 transition-colors">
            <div className="absolute inset-0 bg-gradient-to-t from-primary/5 to-transparent pointer-events-none" />
            <div className="text-center">
              <BrainCircuit className="w-20 h-20 text-primary/30 mx-auto mb-4 group-hover:text-primary/50 transition-colors duration-500" />
              <div className="font-semibold text-lg text-slate-700 dark:text-slate-300">DOHA-TOWER-001</div>
              <div className="text-sm opacity-60">Neural Operating System Online</div>
            </div>
          </div>
        </div>
      </div>

      {/* 30% K2-Think X-Ray Sidebar */}
      <div className="w-[30%] h-full flex flex-col">
        <div className="glass-panel rounded-3xl p-6 flex-1 flex flex-col overflow-hidden shadow-xl border border-white/20 dark:border-white/5">
          <h2 className="text-xl font-bold mb-6 flex items-center justify-between font-mono tracking-tight pb-4 border-b border-black/5 dark:border-white/5">
            <div className="flex items-center gap-2">
              <Cpu className="text-primary" /> <span className="bg-clip-text text-transparent bg-gradient-to-r from-primary to-cta">ARVIS Live Intelligence</span>
            </div>
            <Rss className={`w-4 h-4 ${connected ? 'text-primary animate-pulse' : 'text-slate-400'}`} />
          </h2>

          <LogViewer logs={logs} />
        </div>
      </div>
    </Layout>
  );
}

export default App;
