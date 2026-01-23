
"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FileText, Download, CheckCircle } from "lucide-react";
import { generateGSASReport } from "@/lib/api";

export default function GSASPage() {
    const [downloading, setDownloading] = useState(false);

    async function handleDownload() {
        setDownloading(true);
        try {
            const result = await generateGSASReport();

            if (result && result.status === 'success') {
                const filename = result.pdf_path.split(/[\\/]/).pop();
                if (filename) {
                    window.open(`http://localhost:8001/api/v1/reports/download/${filename}`, '_blank');
                } else {
                    alert("Report generated but filename invalid.");
                }
            } else {
                alert("Failed to generate report. Please check backend logs.");
            }
        } catch (e) {
            console.error(e);
            alert("Error generating report");
        } finally {
            setDownloading(false);
        }
    }

    return (
        <div className="flex-1 space-y-4 p-8 pt-6">
            <div className="flex items-center justify-between space-y-2">
                <h2 className="text-3xl font-bold tracking-tight">GSAS Compliance</h2>
                <div className="flex items-center space-x-2">
                    <Badge className="bg-green-600 text-lg py-1">3-Star Certified</Badge>
                </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Overall Score</CardTitle>
                        <FileText className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">1.82</div>
                        <p className="text-xs text-muted-foreground">Target: 2.0</p>
                    </CardContent>
                </Card>
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Energy Score</CardTitle>
                        <div className="h-4 w-4 rounded-full bg-yellow-500" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">Good</div>
                        <p className="text-xs text-muted-foreground">Requires optimization</p>
                    </CardContent>
                </Card>
            </div>

            <Card>
                <CardHeader>
                    <CardTitle>Certification Reports</CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="flex flex-col gap-4">
                        <div className="flex items-center justify-between p-4 border rounded-lg">
                            <div className="flex items-center gap-4">
                                <FileText className="h-8 w-8 text-blue-500" />
                                <div>
                                    <h3 className="font-semibold">GSAS Operations - Monthly Report (Jan 2026)</h3>
                                    <p className="text-sm text-muted-foreground">Ready for generation</p>
                                </div>
                            </div>
                            <Button variant="outline" onClick={handleDownload} disabled={downloading}>
                                {downloading ? (
                                    <span className="flex items-center gap-2">Generating...</span>
                                ) : (
                                    <><Download className="mr-2 h-4 w-4" /> Generate & Download PDF</>
                                )}
                            </Button>
                        </div>
                    </div>
                </CardContent>
            </Card>
        </div>
    );
}
