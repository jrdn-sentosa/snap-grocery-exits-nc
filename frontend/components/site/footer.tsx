export function Footer() {
  return (
    <footer className="no-print mt-16 border-t-2 border-ink bg-paper">
      <div className="mx-auto flex max-w-[1440px] flex-col gap-2 px-4 py-6 text-sm text-ink-2 md:flex-row md:items-center md:justify-between md:px-5">
        <p>Scores are statistical estimates as of Jan 1, 2024, not a forecast about any owner. Model served with FastAPI on Modal; site on Vercel.</p>
        <a className="underline underline-offset-2" href="https://github.com/jrdn-sentosa/snap-grocery-exits-nc">
          Code on GitHub
        </a>
      </div>
    </footer>
  );
}
