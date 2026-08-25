import { ReactNode } from "react";

interface LayoutProps {
  children: ReactNode;
}

export function DashboardLayout({ children }: LayoutProps) {
  return (
    <div className="w-full min-h-screen">
      <header className="sticky top-0 z-50 border-b border-line bg-bg-0/80 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4">
          <div className="flex items-center gap-8">
            <h1 className="text-xl font-bold tracking-tight text-text">
              Polymeteo
            </h1>
            <nav className="hidden md:flex gap-6">
              <NavLink href="/">Dashboard</NavLink>
              <NavLink href="/markets">Markets</NavLink>
              <NavLink href="/positions">Positions</NavLink>
              <NavLink href="/analytics">Analytics</NavLink>
              <NavLink href="/wallets">Wallets</NavLink>
              <NavLink href="/signals">Signals</NavLink>
              <NavLink href="/settings">Settings</NavLink>
            </nav>
          </div>
          <div className="flex items-center gap-4">
            <StatusIndicator />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}

function NavLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      className="text-sm font-medium text-muted transition-colors hover:text-text"
    >
      {children}
    </a>
  );
}

function StatusIndicator() {
  return (
    <div className="flex items-center gap-2 rounded-full border border-line bg-bg-1 px-3 py-1.5">
      <span className="h-2 w-2 rounded-full bg-mint animate-pulse" />
      <span className="font-mono text-xs text-muted">Connected</span>
    </div>
  );
}

export function MetricCard({
  label,
  value,
  sub,
  trend,
}: {
  label: string;
  value: string;
  sub?: string;
  trend?: "up" | "down" | "neutral";
}) {
  return (
    <div className="rounded-xl border border-line bg-bg-1/50 p-4">
      <span className="text-xs text-muted">{label}</span>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-bold font-mono text-text">{value}</span>
        {trend && (
          <span
            className={`text-xs ${
              trend === "up"
                ? "text-mint"
                : trend === "down"
                ? "text-rose"
                : "text-muted"
            }`}
          >
            {trend === "up" ? "↑" : trend === "down" ? "↓" : "→"}
          </span>
        )}
      </div>
      {sub && <span className="text-xs text-muted">{sub}</span>}
    </div>
  );
}

export function Panel({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl border border-line bg-gradient-to-b from-bg-2/90 to-bg-1/95 p-5 shadow-lg ${className}`}
    >
      {title && <h2 className="mb-4 text-sm font-semibold text-text">{title}</h2>}
      {children}
    </div>
  );
}

export function Badge({
  variant = "default",
  children,
}: {
  variant?: "default" | "primary" | "secondary";
  children: ReactNode;
}) {
  const variants = {
    default: "border-line text-muted",
    primary: "border-cyan/30 text-cyan bg-cyan-soft",
    secondary: "border-amber/30 text-amber bg-amber/10",
  };

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-xs ${variants[variant]}`}
    >
      {children}
    </span>
  );
}
