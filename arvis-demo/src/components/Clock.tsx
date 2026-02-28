import React, { useState, useEffect } from 'react';

export default function Clock() {
    const [time, setTime] = useState(new Date());

    useEffect(() => {
        const timer = setInterval(() => setTime(new Date()), 1000);
        return () => clearInterval(timer);
    }, []);

    return (
        <div className="flex items-center gap-3 text-sm font-mono opacity-80 mr-4">
            <span>{time.toLocaleDateString()}</span>
            <span className="font-bold tracking-widest">{time.toLocaleTimeString()}</span>
        </div>
    );
}
