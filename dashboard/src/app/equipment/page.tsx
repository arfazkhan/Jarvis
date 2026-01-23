
"use client";

import { useEffect, useState } from "react";
import { fetchEquipmentList } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";

interface Equipment {
    equipment_id: string;
    name: string;
    equipment_type: string;
    status: string;
    location: string;
    runtime_hours: number;
    efficiency: number;
    active_alarms: number;
}

export default function EquipmentPage() {
    const [equipment, setEquipment] = useState<Equipment[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState("");

    useEffect(() => {
        async function load() {
            const data = await fetchEquipmentList();
            if (data) setEquipment(data);
            setLoading(false);
        }
        load();

        // Poll every 10 seconds for status updates
        const interval = setInterval(load, 10000);
        return () => clearInterval(interval);
    }, []);

    const filteredEquipment = equipment.filter(e =>
        e.name.toLowerCase().includes(search.toLowerCase()) ||
        e.equipment_id.toLowerCase().includes(search.toLowerCase()) ||
        e.location.toLowerCase().includes(search.toLowerCase())
    );

    const getStatusColor = (status: string) => {
        switch (status.toLowerCase()) {
            case 'running': return 'bg-green-500 hover:bg-green-600';
            case 'fault': return 'bg-red-500 hover:bg-red-600';
            case 'stopped': return 'bg-gray-500 hover:bg-gray-600';
            default: return 'bg-blue-500 hover:bg-blue-600';
        }
    };

    return (
        <div className="flex-1 space-y-4 p-8 pt-6">
            <div className="flex items-center justify-between space-y-2">
                <h2 className="text-3xl font-bold tracking-tight">Equipment Inventory</h2>
                <div className="flex items-center space-x-2">
                    <Badge variant="outline" className="text-lg py-1">
                        Total: {equipment.length}
                    </Badge>
                    <Badge variant="outline" className="text-lg py-1 bg-green-50 text-green-700 border-green-200">
                        Running: {equipment.filter(e => e.status === 'running').length}
                    </Badge>
                    <Badge variant="outline" className="text-lg py-1 bg-red-50 text-red-700 border-red-200">
                        Fault: {equipment.filter(e => e.status === 'fault').length}
                    </Badge>
                </div>
            </div>

            <Card>
                <CardHeader>
                    <div className="flex items-center justify-between">
                        <CardTitle>All Assets</CardTitle>
                        <div className="relative w-72">
                            <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                            <Input
                                placeholder="Search equipment..."
                                className="pl-8"
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                            />
                        </div>
                    </div>
                </CardHeader>
                <CardContent>
                    {loading ? (
                        <div className="p-8 text-center text-muted-foreground">Loading assets...</div>
                    ) : (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>ID</TableHead>
                                    <TableHead>Name</TableHead>
                                    <TableHead>Type</TableHead>
                                    <TableHead>Location</TableHead>
                                    <TableHead>Status</TableHead>
                                    <TableHead className="text-right">Runtime (hrs)</TableHead>
                                    <TableHead className="text-right">Efficiency</TableHead>
                                    <TableHead className="text-right">Alarms</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {filteredEquipment.map((item) => (
                                    <TableRow key={item.equipment_id}>
                                        <TableCell className="font-medium">{item.equipment_id}</TableCell>
                                        <TableCell>{item.name}</TableCell>
                                        <TableCell className="capitalize">{item.equipment_type}</TableCell>
                                        <TableCell>{item.location}</TableCell>
                                        <TableCell>
                                            <Badge className={getStatusColor(item.status)}>
                                                {item.status}
                                            </Badge>
                                        </TableCell>
                                        <TableCell className="text-right">{item.runtime_hours.toFixed(1)}</TableCell>
                                        <TableCell className="text-right">{(item.efficiency * 100).toFixed(0)}%</TableCell>
                                        <TableCell className="text-right">
                                            {item.active_alarms > 0 ? (
                                                <Badge variant="destructive">{item.active_alarms}</Badge>
                                            ) : (
                                                <span className="text-muted-foreground">-</span>
                                            )}
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
