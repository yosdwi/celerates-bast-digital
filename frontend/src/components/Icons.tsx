import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const common = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export function MenuIcon(props: IconProps) {
  return <svg {...common} {...props}><path d="M4 7h16M4 12h16M4 17h16" /></svg>;
}

export function SearchIcon(props: IconProps) {
  return <svg {...common} {...props}><circle cx="11" cy="11" r="6" /><path d="m16 16 4 4" /></svg>;
}

export function SparkleIcon(props: IconProps) {
  return <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...props}><path d="m12 2 1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8L12 2Z" /><path d="m18.5 14 .9 2.6L22 17.5l-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9.9-2.6Z" /></svg>;
}

export function GridIcon(props: IconProps) {
  return <svg {...common} {...props}><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" /></svg>;
}

export function PersonIcon(props: IconProps) {
  return <svg {...common} {...props}><circle cx="12" cy="8" r="3.2" /><path d="M5 20c.7-4 3-6 7-6s6.3 2 7 6" /></svg>;
}

export function TrendIcon(props: IconProps) {
  return <svg {...common} {...props}><path d="m4 17 5-5 4 3 7-8" /><path d="M20 7v5h-5" /></svg>;
}

export function CheckDocIcon(props: IconProps) {
  return <svg {...common} {...props}><path d="M6 3h9l3 3v15H6z" /><path d="m9 13 2 2 4-4" /></svg>;
}

export function AlertIcon(props: IconProps) {
  return <svg {...common} {...props}><circle cx="12" cy="12" r="9" /><path d="M12 7v6" /><circle cx="12" cy="17" r=".8" fill="currentColor" stroke="none" /></svg>;
}

export function SyncIcon(props: IconProps) {
  return <svg {...common} {...props}><path d="M20 7h-5V2" /><path d="M20 7a8 8 0 1 0 1 8" /></svg>;
}

export function ClockIcon(props: IconProps) {
  return <svg {...common} {...props}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></svg>;
}

export function ExternalIcon(props: IconProps) {
  return <svg {...common} {...props}><path d="M9 5H5v14h14v-4" /><path d="M13 5h6v6" /><path d="m19 5-9 9" /></svg>;
}

export function SettingsIcon(props: IconProps) {
  return <svg {...common} {...props}><circle cx="12" cy="12" r="3" /><path d="M4 12h2M18 12h2M12 4v2M12 18v2" /></svg>;
}

export function ChevronIcon(props: IconProps) {
  return <svg {...common} {...props}><path d="m9 6 6 6-6 6" /></svg>;
}

export function CloseIcon(props: IconProps) {
  return <svg {...common} {...props}><path d="m6 6 12 12M18 6 6 18" /></svg>;
}

export function RefreshIcon(props: IconProps) {
  return <svg {...common} {...props}><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4v7h-7" /></svg>;
}
