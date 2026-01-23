
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { fetchDashboardOverview } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, AlertTriangle, Zap, Server } from "lucide-react";
import { CopilotChat } from "@/components/dashboard/copilot-chat";

interface DashboardData {
  equipment_total: number;
  equipment_running: number;
  active_alarms_total: number;
  active_alarms_critical: number;
  energy_today_kwh: number;
  maintenance_due_7d: number;
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const result = await fetchDashboardOverview();
      if (result) setData(result);
      setLoading(false);
    }
    load();

    // Poll every 5 seconds
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  if (loading && !data) return <div className="p-8">Loading dashboard...</div>;

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      <div className="flex items-center justify-between space-y-2">
        <h2 className="text-3xl font-bold tracking-tight">ARVIS Ops Copilot</h2>
        <div className="flex items-center space-x-2">
          <span className="text-sm text-gray-500">Live Connection: {data ? 'Online' : 'Offline'}</span>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              <Link href="/equipment" className="hover:underline flex items-center gap-1">
                Total Equipment <Server className="h-3 w-3 inline" />
              </Link>
            </CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.equipment_total || 0}</div>
            <p className="text-xs text-muted-foreground">
              {data ? `${data.equipment_running} Running` : 'Loading...'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              <Link href="/alarms" className="hover:underline flex items-center gap-1">
                Active Alarms <AlertTriangle className="h-3 w-3 inline" />
              </Link>
            </CardTitle>
            <AlertTriangle className={`h-4 w-4 ${data?.active_alarms_total ? 'text-red-500' : 'text-muted-foreground'}`} />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.active_alarms_total || 0}</div>
            <p className="text-xs text-muted-foreground">
              {data?.active_alarms_critical || 0} Critical
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              <Link href="/energy" className="hover:underline flex items-center gap-1">
                Energy Today <Zap className="h-3 w-3 inline" />
              </Link>
            </CardTitle>
            <Zap className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.energy_today_kwh.toFixed(1) || "0.0"} kWh</div>
            <p className="text-xs text-muted-foreground">
              +2.1% from yesterday
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Maintenance Due
            </CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.maintenance_due_7d || 0}</div>
            <p className="text-xs text-muted-foreground">
              In next 7 days
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
        <Card className="col-span-4">
          <CardHeader>
            <CardTitle>Overview</CardTitle>
          </CardHeader>
          <CardContent className="pl-2">
            <div className="h-[200px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={[
                  { name: 'Chillers', total: 4, running: 3 },
                  { name: 'AHUs', total: 8, running: 6 },
                  { name: 'Pumps', total: 6, running: 6 },
                  { name: 'Fans', total: 12, running: 10 },
                ]}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="total" fill="#e2e8f0" name="Total" />
                  <Bar dataKey="running" fill="#3b82f6" name="Running" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <CopilotChat />
      </div>
    </div>
  );
}
