
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { LayoutDashboard, Server, AlertTriangle, Zap, Settings, FileText } from "lucide-react";

export function Sidebar() {
    const pathname = usePathname();

    return (
        <div className="pb-12 w-64 border-r min-h-screen bg-gray-50/40 hidden md:block">
            <div className="space-y-4 py-4">
                <div className="px-3 py-2">
                    <h2 className="mb-2 px-4 text-lg font-semibold tracking-tight text-blue-600">
                        ARVIS Ops
                    </h2>
                    <div className="space-y-1">
                        <Button asChild variant={pathname === "/" ? "secondary" : "ghost"} className="w-full justify-start">
                            <Link href="/">
                                <LayoutDashboard className="mr-2 h-4 w-4" />
                                Dashboard
                            </Link>
                        </Button>
                        <Button asChild variant={pathname.startsWith("/equipment") ? "secondary" : "ghost"} className="w-full justify-start">
                            <Link href="/equipment">
                                <Server className="mr-2 h-4 w-4" />
                                Equipment
                            </Link>
                        </Button>
                        <Button asChild variant={pathname.startsWith("/alarms") ? "secondary" : "ghost"} className="w-full justify-start">
                            <Link href="/alarms">
                                <AlertTriangle className="mr-2 h-4 w-4" />
                                Alarms
                            </Link>
                        </Button>
                        <Button asChild variant={pathname.startsWith("/energy") ? "secondary" : "ghost"} className="w-full justify-start">
                            <Link href="/energy">
                                <Zap className="mr-2 h-4 w-4" />
                                Energy
                            </Link>
                        </Button>
                        <Button asChild variant={pathname.startsWith("/gsas") ? "secondary" : "ghost"} className="w-full justify-start">
                            <Link href="/gsas">
                                <FileText className="mr-2 h-4 w-4" />
                                GSAS Report
                            </Link>
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    );
}
