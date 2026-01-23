
"use client";

import { useEffect, useState } from "react";
import { fetchActiveAlarms, acknowledgeAlarm } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { CheckCircle, AlertTriangle, Info } from "lucide-react";

interface Alarm {
    alarm_id: string;
    equipment_id: string;
    message: string;
    severity: string;
    state: string;
    triggered_at: string;
    duration_minutes: number;
}

export default function AlarmsPage() {
    const [alarms, setAlarms] = useState<Alarm[]>([]);
    const [loading, setLoading] = useState(true);

    async function load() {
        const data = await fetchActiveAlarms();
        if (data) setAlarms(data);
        setLoading(false);
    }

    useEffect(() => {
        load();
        const interval = setInterval(load, 5000);
        return () => clearInterval(interval);
    }, []);

    async function handleAcknowledge(id: string) {
        await acknowledgeAlarm(id);
        load(); // Refresh list immediately
    }

    const getSeverityBadge = (severity: string) => {
        switch (severity.toLowerCase()) {
            case "critical":
                return <Badge variant="destructive">CRITICAL</Badge>;
            case "high":
                return <Badge className="bg-orange-500 hover:bg-orange-600">HIGH</Badge>;
            case "medium":
                return <Badge className="bg-yellow-500 hover:bg-yellow-600">MEDIUM</Badge>;
            default:
                return <Badge variant="secondary">LOW</Badge>;
        }
    };

    return (
        <div className="flex-1 space-y-4 p-8 pt-6">
            <div className="flex items-center justify-between space-y-2">
                <h2 className="text-3xl font-bold tracking-tight">Active Alarms</h2>
                <div className="flex items-center space-x-2">
                    <Button onClick={() => load()}>
                        Refresh
                    </Button>
                </div>
            </div>

            <div className="grid gap-4 md:grid-cols-3 mb-4">
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Critical Alarms</CardTitle>
                        <AlertTriangle className="h-4 w-4 text-red-500" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold text-red-500">
                            {alarms.filter(a => a.severity === 'critical').length}
                        </div>
                    </CardContent>
                </Card>
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Total Active</CardTitle>
                        <AlertTriangle className="h-4 w-4 text-yellow-500" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">
                            {alarms.length}
                        </div>
                    </CardContent>
                </Card>
            </div>

            <Card>
                <CardHeader>
                    <CardTitle>Alarm List</CardTitle>
                </CardHeader>
                <CardContent>
                    {loading ? (
                        <div className="text-center p-8">Loading alarms...</div>
                    ) : alarms.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                            <CheckCircle className="h-12 w-12 mb-4 text-green-500" />
                            <p>No active alarms. System is healthy.</p>
                        </div>
                    ) : (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Severity</TableHead>
                                    <TableHead>Time</TableHead>
                                    <TableHead>Equipment</TableHead>
                                    <TableHead>Message</TableHead>
                                    <TableHead>Duration</TableHead>
                                    <TableHead>Action</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {alarms.map((alarm) => (
                                    <TableRow key={alarm.alarm_id}>
                                        <TableCell>{getSeverityBadge(alarm.severity)}</TableCell>
                                        <TableCell className="whitespace-nowrap">
                                            {new Date(alarm.triggered_at).toLocaleString()}
                                        </TableCell>
                                        <TableCell className="font-medium">{alarm.equipment_id}</TableCell>
                                        <TableCell>{alarm.message}</TableCell>
                                        <TableCell>{Math.round(alarm.duration_minutes)} min</TableCell>
                                        <TableCell>
                                            <Button variant="outline" size="sm" onClick={() => handleAcknowledge(alarm.alarm_id)}>
                                                Acknowledge
                                            </Button>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}
