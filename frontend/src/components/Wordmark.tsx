export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`flex items-center gap-2.5 ${className}`}>
      <span
        aria-hidden
        className="grid size-8 place-items-center border border-gold-500 font-display text-lg text-gold-500"
      >
        F
      </span>
      <span className="font-display text-xl tracking-tight text-gold-300">Flatons</span>
    </span>
  );
}
