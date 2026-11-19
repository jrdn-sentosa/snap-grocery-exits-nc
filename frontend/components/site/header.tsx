"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MapPin, Menu } from "lucide-react";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { SCORE_DATE_LABEL } from "@/lib/site";

export const NAV = [
  { href: "/", label: "Store map" },
  { href: "/highest-risk", label: "Highest risk" },
  { href: "/check", label: "Check a store" },
  { href: "/how-it-works", label: "How it works" },
] as const;

export function Header() {
  const path = usePathname();
  const current = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <header className="no-print border-b-2 border-ink bg-paper">
      <div className="mx-auto flex max-w-[1440px] items-center gap-6 px-4 py-3 md:px-5">
        <Link href="/" className="flex items-center gap-2.5" aria-label="Grocery Watch home">
          <span className="grid size-8 place-items-center rounded-full bg-forest text-paper-light">
            <MapPin className="size-4" aria-hidden />
          </span>
          <span className="leading-none">
            <span className="block font-wordmark text-xl text-forest">Grocery Watch</span>
            <span className="label-mono mt-0.5 hidden text-[0.625rem] text-ink-2 sm:block">Charlotte · Mecklenburg Co., NC</span>
          </span>
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-5 md:flex">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              aria-current={current(n.href) ? "page" : undefined}
              className={`border-b-2 py-1 text-[0.9375rem] ${current(n.href) ? "border-forest font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink"}`}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <span className="label-mono ml-auto hidden text-ink-2 md:block">{SCORE_DATE_LABEL}</span>
        <Sheet>
          <SheetTrigger className="ml-auto grid size-11 place-items-center rounded-md border border-rule md:hidden" aria-label="Menu">
            <Menu className="size-5" aria-hidden />
          </SheetTrigger>
          <SheetContent side="right" className="bg-paper">
            <SheetTitle className="sr-only">Menu</SheetTitle>
            <nav aria-label="Mobile" className="mt-10 flex flex-col">
              {NAV.map((n) => (
                <Link key={n.href} href={n.href} aria-current={current(n.href) ? "page" : undefined} className="border-b border-rule px-4 py-4 font-serif text-2xl">
                  {n.label}
                </Link>
              ))}
              <span className="label-mono mt-6 px-4 text-ink-2">{SCORE_DATE_LABEL}</span>
            </nav>
          </SheetContent>
        </Sheet>
      </div>
    </header>
  );
}
