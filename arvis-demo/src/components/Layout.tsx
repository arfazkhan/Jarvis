import React from 'react';
import { Moon, Sun } from 'lucide-react';
import BackgroundBlob from './BackgroundBlob';
import Clock from './Clock';

interface LayoutProps {
    children: React.ReactNode;
    isDark: boolean;
    toggleDark: () => void;
}

export default function Layout({ children, isDark, toggleDark }: LayoutProps) {
    return (
        <div className="relative min-h-screen text-slate-800 dark:text-slate-100 selection:bg-primary/30 font-sans">
            <BackgroundBlob />

            {/* Header */}
            <header className="fixed top-0 left-0 right-0 h-16 glass-panel z-50 flex items-center justify-between px-6 shadow-sm border-b">
                <div className="flex items-center space-x-3">
                    <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-primary to-cta flex items-center justify-center font-bold text-white shadow-lg shadow-primary/20">
                        A
                    </div>
                    <span className="font-bold text-xl tracking-tight">ARVIS <span className="text-primary opacity-80 font-medium">Demo</span></span>
                </div>

                <div className="flex items-center">
                    <Clock />
                    <button
                        onClick={toggleDark}
                        className="p-2.5 rounded-full hover:bg-black/5 dark:hover:bg-white/10 transition-colors duration-200"
                        aria-label="Toggle dark mode"
                    >
                        {isDark ? <Sun className="w-5 h-5 text-amber-300" /> : <Moon className="w-5 h-5 text-slate-600" />}
                    </button>
                </div>
            </header>

            {/* Main Content Area */}
            <main className="pt-20 px-6 pb-6 h-screen box-border flex gap-6">
                {children}
            </main>
        </div>
    );
}
