
const API_BASE_URL = 'http://localhost:8001/api/v1';

export async function fetchDashboardOverview() {
  try {
    const res = await fetch(`${API_BASE_URL}/dashboard/overview`);
    if (!res.ok) throw new Error('Failed to fetch dashboard data');
    return await res.json();
  } catch (error) {
    console.error('Error fetching dashboard overview:', error);
    return null;
  }
}

export async function fetchActiveAlarms() {
  try {
    const res = await fetch(`${API_BASE_URL}/dashboard/alarms/active`);
    if (!res.ok) throw new Error('Failed to fetch alarms');
    return await res.json();
  } catch (error) {
    console.error('Error fetching alarms:', error);
    return [];
  }
}

export async function postChatQuery(message: string) {
  try {
    const res = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: message }),
    });
    if (!res.ok) throw new Error('Failed to send chat query');
    return await res.json();
  } catch (error) {
    console.error('Error in chat:', error);
    return { response: "Sorry, I can't connect to the ARVIS backend right now." };
  }
}

export async function fetchEquipmentList() {
  try {
    const res = await fetch(`${API_BASE_URL}/equipment`);
    if (!res.ok) throw new Error('Failed to fetch equipment list');
    return await res.json();
  } catch (error) {
    return [];
  }
}

export async function acknowledgeAlarm(alarmId: string) {
  try {
    const res = await fetch(`${API_BASE_URL}/alarms/${alarmId}/acknowledge`, {
      method: "POST",
    });
    if (!res.ok) throw new Error("Failed to acknowledge alarm");
    return await res.json();
  } catch (error) {
    console.error("Error acknowledging alarm:", error);
    return null;
  }
}

export async function fetchEnergyConsumption(period = "today") {
  try {
    const res = await fetch(`${API_BASE_URL}/energy/consumption?period=${period}`);
    if (!res.ok) throw new Error('Failed to fetch energy');
    return await res.json();
  } catch (error) {
    console.error('Error fetching energy:', error);
    return null;
  }
}

export async function fetchEnergyAnomalies() {
  try {
    const res = await fetch(`${API_BASE_URL}/energy/anomalies`);
    if (!res.ok) throw new Error('Failed to fetch anomalies');
    return await res.json();
  } catch (error) {
    console.error('Error fetching anomalies:', error);
    return [];
  }
}

export async function generateGSASReport() {
  try {
    const res = await fetch(`${API_BASE_URL}/gsas/gord-report`, {
      method: "POST",
    });
    if (!res.ok) throw new Error("Failed to generate report");
    return await res.json();
  } catch (error) {
    console.error("Error generating report:", error);
    return null;
  }
}
