import type { Metadata, Viewport } from "next";
import { Bagel_Fat_One, Fraunces, IBM_Plex_Mono, Inter_Tight, Instrument_Serif } from "next/font/google";
import "./globals.css";
import { Header } from "@/components/site/header";
import { Footer } from "@/components/site/footer";
import { TooltipProvider } from "@/components/ui/tooltip";

const bagel = Bagel_Fat_One({ weight: "400", subsets: ["latin"], variable: "--font-bagel" });
const instrument = Instrument_Serif({ weight: "400", style: ["normal", "italic"], subsets: ["latin"], variable: "--font-instrument" });
const interTight = Inter_Tight({ subsets: ["latin"], variable: "--font-inter-tight" });
const plexMono = IBM_Plex_Mono({ weight: ["400", "500"], subsets: ["latin"], variable: "--font-plex-mono" });
const fraunces = Fraunces({ weight: ["500", "600"], subsets: ["latin"], variable: "--font-fraunces" });

export const metadata: Metadata = {
  title: { default: "Grocery Watch: SNAP grocery exit risk, Charlotte–Mecklenburg", template: "%s · Grocery Watch" },
  description:
    "Which SNAP-authorized grocery stores in Mecklenburg County are most likely to lose SNAP authorization, and who would be left without one nearby. Scores as of Jan 1, 2024.",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${bagel.variable} ${instrument.variable} ${interTight.variable} ${plexMono.variable} ${fraunces.variable}`}>
      <body className="min-h-screen flex flex-col">
        <TooltipProvider>
          <Header />
          <main className="flex-1">{children}</main>
          <Footer />
        </TooltipProvider>
      </body>
    </html>
  );
}
