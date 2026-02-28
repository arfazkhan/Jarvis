import { useState, useEffect } from 'react';

export type LogEntry = {
    id: string;
    timestamp: string;
    type: 'EVENT' | 'REASONING' | 'TOOL_CALL' | 'PLAN' | 'SYSTEM';
    content: string;
    metadata?: any;
};

export function useArvisStream(mock: boolean = true) {
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [connected, setConnected] = useState(false);
    const [metrics, setMetrics] = useState({
        alarms: 0,
        efficiency: 95.5,
        load: 'Normal'
    });

    useEffect(() => {
        if (mock) {
            setConnected(true);

            // Simulate incoming events
            const mockEvents = [
                { type: 'EVENT', delay: 1000, content: 'I noticed the temperature in the lobby is rising above normal.' },
                { type: 'REASONING', delay: 2500, content: 'Looking into this... It seems Chiller 2 has stopped. I should check if other units can compensate.' },
                { type: 'TOOL_CALL', delay: 3500, content: 'Checking current system status...' },
                { type: 'SYSTEM', delay: 4500, content: 'Confirmed. Chiller 1 is available and can handle the extra load.' },
                { type: 'PLAN', delay: 6000, content: 'I have adjusted the flow to Chiller 1. Temperatures should return to normal shortly.' }
            ] as const;

            let currentTime = 1000;
            const timeouts: number[] = [];

            mockEvents.forEach((ev) => {
                const t = window.setTimeout(() => {
                    const now = new Date();
                    const entry: LogEntry = {
                        id: Math.random().toString(36).substring(7),
                        timestamp: now.toISOString().split('T')[1].replace('Z', ''),
                        type: ev.type,
                        content: ev.content
                    };
                    setLogs(prev => [...prev, entry]);

                    if (ev.type === 'EVENT') setMetrics(m => ({ ...m, alarms: m.alarms + 1 }));
                    if (ev.type === 'PLAN') setMetrics(m => ({ ...m, alarms: Math.max(0, m.alarms - 1), efficiency: 96.1 }));

                }, ev.delay);
                timeouts.push(t);
            });

            return () => timeouts.forEach((t) => window.clearTimeout(t));
        }
    }, [mock]);

    return { logs, metrics, connected };
}
