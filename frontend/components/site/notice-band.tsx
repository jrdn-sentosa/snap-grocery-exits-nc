import Link from "next/link";
import { Scissors } from "lucide-react";

/** USDA stocking standards: compliance date Nov 4, 2026 has passed, so the notice speaks in the present tense. */
export function NoticeBand({ className }: { className?: string }) {
  return (
    <div role="note" className={`relative border-2 border-dashed border-mustard-text/60 bg-notice px-4 py-3 pl-5 ${className ?? ""}`}>
      <Scissors aria-hidden className="absolute -top-2.5 left-3 size-4 bg-paper text-mustard-text" />
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        <span className="label-mono border border-mustard-text px-2 py-0.5 font-medium text-mustard-text">In effect since Nov 4, 2026</span>
        <span>
          <strong>New USDA stocking standards.</strong> Every SNAP store must now carry 7 varieties in each of 4 staple food groups. Our model was trained on earlier years and doesn’t
          account for this.{" "}
          <Link href="/how-it-works#limits" className="font-medium underline underline-offset-2">
            What this means
          </Link>
        </span>
      </p>
    </div>
  );
}
