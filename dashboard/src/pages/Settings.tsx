import { useState } from "react";
import { DashboardLayout, Panel, Badge } from "../components/DashboardLayout";

const settingsSections = [
  { id: "general", label: "General", description: "Basic app settings" },
  { id: "trading", label: "Trading", description: "Trading parameters" },
  { id: "notifications", label: "Notifications", description: "Alert preferences" },
  { id: "api", label: "API Keys", description: "External integrations" },
  { id: "risk", label: "Risk Management", description: "Position limits" },
  { id: "advanced", label: "Advanced", description: "Expert settings" },
];

const apiKeys = [
  { name: "Polymarket API", status: "active", key: "pk_live_••••••••••••" },
  { name: "OpenAI API", status: "active", key: "sk-••••••••••••••••" },
  { name: "Alchemy RPC", status: "active", key: "••••••••••••••••••" },
];

export default function Settings() {
  const [activeSection, setActiveSection] = useState("general");
  const [settings, setSettings] = useState({
    autoTrade: true,
    maxPositionSize: 5000,
    stopLossPercent: 2.0,
    takeProfitPercent: 5.0,
    signalConfidence: 0.7,
    notifications: true,
    emailAlerts: true,
    telegramAlerts: false,
  });

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-text">Settings</h1>
          <p className="text-sm text-muted">Configure your trading preferences</p>
        </div>

        <div className="grid gap-6 lg:grid-cols-4">
          <div className="lg:col-span-1">
            <Panel title="Categories">
              <div className="space-y-1">
                {settingsSections.map((section) => (
                  <button
                    key={section.id}
                    onClick={() => setActiveSection(section.id)}
                    className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                      activeSection === section.id
                        ? "bg-cyan/20 text-cyan"
                        : "text-muted hover:bg-bg-0 hover:text-text"
                    }`}
                  >
                    <p className="font-medium">{section.label}</p>
                    <p className="text-xs opacity-70">{section.description}</p>
                  </button>
                ))}
              </div>
            </Panel>
          </div>

          <div className="lg:col-span-3 space-y-6">
            {activeSection === "general" && (
              <>
                <Panel title="General Settings">
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="font-medium text-text">Auto Trading</p>
                        <p className="text-xs text-muted">Automatically execute signals</p>
                      </div>
                      <button
                        onClick={() =>
                          setSettings((s) => ({ ...s, autoTrade: !s.autoTrade }))
                        }
                        className={`h-6 w-11 rounded-full transition-colors ${
                          settings.autoTrade ? "bg-cyan" : "bg-line"
                        }`}
                      >
                        <div
                          className={`h-4 w-4 rounded-full bg-white transition-transform ${
                            settings.autoTrade ? "translate-x-6" : "translate-x-1"
                          }`}
                        />
                      </button>
                    </div>
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="font-medium text-text">Notifications</p>
                        <p className="text-xs text-muted">Desktop notifications</p>
                      </div>
                      <button
                        onClick={() =>
                          setSettings((s) => ({ ...s, notifications: !s.notifications }))
                        }
                        className={`h-6 w-11 rounded-full transition-colors ${
                          settings.notifications ? "bg-cyan" : "bg-line"
                        }`}
                      >
                        <div
                          className={`h-4 w-4 rounded-full bg-white transition-transform ${
                            settings.notifications ? "translate-x-6" : "translate-x-1"
                          }`}
                        />
                      </button>
                    </div>
                  </div>
                </Panel>

                <Panel title="Alert Preferences">
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="font-medium text-text">Email Alerts</p>
                        <p className="text-xs text-muted">Send alerts via email</p>
                      </div>
                      <button
                        onClick={() =>
                          setSettings((s) => ({ ...s, emailAlerts: !s.emailAlerts }))
                        }
                        className={`h-6 w-11 rounded-full transition-colors ${
                          settings.emailAlerts ? "bg-cyan" : "bg-line"
                        }`}
                      >
                        <div
                          className={`h-4 w-4 rounded-full bg-white transition-transform ${
                            settings.emailAlerts ? "translate-x-6" : "translate-x-1"
                          }`}
                        />
                      </button>
                    </div>
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="font-medium text-text">Telegram Alerts</p>
                        <p className="text-xs text-muted">Send alerts via Telegram</p>
                      </div>
                      <button
                        onClick={() =>
                          setSettings((s) => ({ ...s, telegramAlerts: !s.telegramAlerts }))
                        }
                        className={`h-6 w-11 rounded-full transition-colors ${
                          settings.telegramAlerts ? "bg-cyan" : "bg-line"
                        }`}
                      >
                        <div
                          className={`h-4 w-4 rounded-full bg-white transition-transform ${
                            settings.telegramAlerts ? "translate-x-6" : "translate-x-1"
                          }`}
                        />
                      </button>
                    </div>
                  </div>
                </Panel>
              </>
            )}

            {activeSection === "trading" && (
              <Panel title="Trading Parameters">
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-text mb-2">
                      Max Position Size ($)
                    </label>
                    <input
                      type="number"
                      value={settings.maxPositionSize}
                      onChange={(e) =>
                        setSettings((s) => ({
                          ...s,
                          maxPositionSize: Number(e.target.value),
                        }))
                      }
                      className="w-full rounded-lg border border-line bg-bg-0 px-4 py-2 font-mono text-text focus:border-cyan focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-text mb-2">
                      Signal Confidence Threshold
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.1"
                      value={settings.signalConfidence}
                      onChange={(e) =>
                        setSettings((s) => ({
                          ...s,
                          signalConfidence: Number(e.target.value),
                        }))
                      }
                      className="w-full"
                    />
                    <p className="text-right font-mono text-sm text-cyan">
                      {(settings.signalConfidence * 100).toFixed(0)}%
                    </p>
                  </div>
                </div>
              </Panel>
            )}

            {activeSection === "api" && (
              <Panel title="API Keys">
                <div className="space-y-3">
                  {apiKeys.map((api) => (
                    <div
                      key={api.name}
                      className="flex items-center justify-between rounded-lg border border-line bg-bg-0/50 p-4"
                    >
                      <div>
                        <p className="font-medium text-text">{api.name}</p>
                        <p className="font-mono text-sm text-muted">{api.key}</p>
                      </div>
                      <Badge variant="primary">{api.status}</Badge>
                    </div>
                  ))}
                </div>
              </Panel>
            )}

            {activeSection === "risk" && (
              <Panel title="Risk Management">
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-text mb-2">
                      Stop Loss (%)
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      value={settings.stopLossPercent}
                      onChange={(e) =>
                        setSettings((s) => ({
                          ...s,
                          stopLossPercent: Number(e.target.value),
                        }))
                      }
                      className="w-full rounded-lg border border-line bg-bg-0 px-4 py-2 font-mono text-text focus:border-cyan focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-text mb-2">
                      Take Profit (%)
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      value={settings.takeProfitPercent}
                      onChange={(e) =>
                        setSettings((s) => ({
                          ...s,
                          takeProfitPercent: Number(e.target.value),
                        }))
                      }
                      className="w-full rounded-lg border border-line bg-bg-0 px-4 py-2 font-mono text-text focus:border-cyan focus:outline-none"
                    />
                  </div>
                </div>
              </Panel>
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
