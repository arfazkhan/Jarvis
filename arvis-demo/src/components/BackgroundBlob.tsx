import React from 'react';

export default function BackgroundBlob() {
    return (
        <div className="fixed inset-0 overflow-hidden pointer-events-none -z-10">
            <div
                className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] rounded-full bg-primary/20 dark:bg-primary/50 blur-[120px] animate-pulse"
                style={{ animationDuration: '8s' }}
            />
            <div
                className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-full bg-secondary/20 dark:bg-cta/30 blur-[120px] animate-pulse"
                style={{ animationDuration: '12s', animationDelay: '2s' }}
            />
        </div>
    );
}
