import type { DashboardPayload } from './types'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export async function fetchDashboard(): Promise<DashboardPayload> {
  const res = await fetch(`${API_BASE}/api/dashboard`)
  if (!res.ok) {
    throw new Error(`Dashboard API failed: ${res.status}`)
  }
  return res.json()
}
