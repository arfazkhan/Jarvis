
"use client";

import { useEffect, useState } from "react";
import { fetchEnergyConsumption, fetchEnergyAnomalies } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Zap, TrendingUp, AlertOctagon } from "lucide-react";
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    LineChart,
    Line,
} from "recharts";

interface EnergyData {
    period: string;
    total_kwh: number;
    baseline_kwh: number;
    deviation_percent: number;
    peak_kw: number;
    peak_time: string;
    cost_qar: number;
}

interface Anomaly {
    pattern_id: string;
    pattern_type: string;
    description: string;
    estimated_savings_qar: number;
    occurrences: number;
}

// Mock chart data - in real app, fetch history
const HOURLY_DATA = [
    { time: "00:00", kwh: 120 }, { time: "04:00", kwh: 110 },
    { time: "08:00", kwh: 350 }, { time: "12:00", kwh: 480 },
    { time: "16:00", kwh: 420 }, { time: "20:00", kwh: 280 },
];

export default function EnergyPage() {
    const [data, setData] = useState<EnergyData | null>(null);
    const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        async function load() {
            const [energy, anom] = await Promise.all([
                fetchEnergyConsumption(),
                fetchEnergyAnomalies()
            ]);
            if (energy) setData(energy);
            if (anom) setAnomalies(anom);
            setLoading(false);
        }
        load();
    }, []);

    if (loading) return <div className="p-8">Loading energy analytics...</div>;

    return (
        <div className="flex-1 space-y-4 p-8 pt-6">
            <div className="flex items-center justify-between space-y-2">
                <h2 className="text-3xl font-bold tracking-tight">Energy Analytics</h2>
                <div className="flex items-center space-x-2">
                    <Badge variant="outline" className="text-lg py-1 border-yellow-500 text-yellow-600">
                        Today's Cost: {data?.cost_qar} QAR
                    </Badge>
                </div>
            </div>

            <div className="grid gap-4 md:grid-cols-4">
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Consumption</CardTitle>
                        <Zap className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">{data?.total_kwh} kWh</div>
                        <p className="text-xs text-muted-foreground">
                            {data?.deviation_percent > 0 ? '+' : ''}{data?.deviation_percent}% vs baseline
                        </p>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Peak Demand</CardTitle>
                        <TrendingUp className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">{data?.peak_kw} kW</div>
                        <p className="text-xs text-muted-foreground">
                            at {data?.peak_time}
                        </p>
                    </CardContent>
                </Card>

                <Card className="col-span-2">
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Waste Anomalies</CardTitle>
                        <AlertOctagon className="h-4 w-4 text-red-500" />
                    </CardHeader>
                    <CardContent>
                        <div className="space-y-2">
                            {anomalies.length === 0 ? (
                                <p className="text-sm text-muted-foreground">No waste patterns detected.</p>
                            ) : (
                                anomalies.map((a, i) => (
                                    <div key={i} className="flex justify-between items-center text-sm">
                                        <span>{a.description}</span>
                                        <Badge variant="destructive">Save {a.estimated_savings_qar} QAR</Badge>
                                    </div>
                                ))
                            )}
                        </div>
                    </CardContent>
                </Card>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
                <Card className="col-span-2 md:col-span-1">
                    <CardHeader>
                        <CardTitle>Hourly Consumption (Today)</CardTitle>
                    </CardHeader>
                    <CardContent className="pl-2">
                        <ResponsiveContainer width="100%" height={300}>
                            <BarChart data={HOURLY_DATA}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="time" />
                                <YAxis />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#fff', borderRadius: '8px', border: '1px solid #ccc' }}
                                    labelStyle={{ color: '#333' }}
                                />
                                <Bar dataKey="kwh" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </CardContent>
                </Card>

                <Card className="col-span-2 md:col-span-1">
                    <CardHeader>
                        <CardTitle>Energy vs Baseline</CardTitle>
                    </CardHeader>
                    <CardContent className="pl-2">
                        <ResponsiveContainer width="100%" height={300}>
                            <LineChart data={HOURLY_DATA}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="time" />
                                <YAxis />
                                <Tooltip />
                                <Line type="monotone" dataKey="kwh" stroke="#8884d8" strokeWidth={2} />
                                <Line type="monotone" dataKey="kwh" stroke="#82ca9d" strokeDasharray="5 5" name="Baseline" />
                            </LineChart>
                        </ResponsiveContainer>
                    </CardContent>
                </Card>
            </div>
        </div>
    );
}
