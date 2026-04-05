import { cn } from "@/lib/utils";

/** Concentric-pulse loader used while a scan is pending/running.
 * Subtle, animation driven by CSS keyframes in globals.css. */
export function ScanLoader({ className }: { className?: string }) {
  return (
    <div
      className={cn("pulse-loader", className)}
      role="status"
      aria-label="Scan in progress"
    >
      <span className="ring" />
      <span className="ring" />
      <span className="ring" />
      <span className="core" />
    </div>
  );
}
