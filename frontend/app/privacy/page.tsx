import Navbar from "@/components/Navbar";

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-[720px] mx-auto px-4 py-6">
        <h1 className="text-h1 font-bold text-text mb-6">Privacy</h1>

        <div className="space-y-6">
          <section>
            <h2 className="text-h2 font-bold text-text mb-3">Comments</h2>
            <p className="text-body text-text leading-body mb-3">
              Comments on this site are powered by Giscus, a GitHub-based comment system. To post a comment, you must sign in with your GitHub account through Giscus.
            </p>
            <p className="text-body text-text leading-body mb-3">
              When you use the comment widget, GitHub processes your IP address and browser information to load the widget and authenticate your account. This is handled entirely by GitHub and Giscus — this site does not collect or store that information.
            </p>
            <p className="text-body text-text leading-body">
              All comments you submit are public and stored as GitHub Discussions in the <a href="https://github.com/Sohan2005/the-problem-network-comments" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors">Sohan2005/the-problem-network-comments</a> repository under the "Brief Comments" category. Comments are not stored in this site's own database.
            </p>
          </section>

          <section>
            <h2 className="text-h2 font-bold text-text mb-3">Saved Projects</h2>
            <p className="text-body text-text leading-body">
              Your favorited projects are stored locally in your browser's localStorage. This data persists only on your device and is not transmitted to or stored by this site's servers. If you clear your browser data or switch devices, your saved projects will be lost.
            </p>
          </section>

          <section>
            <h2 className="text-h2 font-bold text-text mb-3">Contact</h2>
            <p className="text-body text-text leading-body">
              If you have questions about this privacy policy or how your data is handled, please open an issue on the <a href="https://github.com/Sohan2005/the-problem-network" target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover transition-colors">main project repository</a>.
            </p>
          </section>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-bg-alt py-6 mt-8">
        <div className="max-w-7xl mx-auto px-4 text-center text-text-muted text-sm">
          <p>The Problem Network — Translating real-world technical problems into junior-dev-friendly briefs</p>
        </div>
      </footer>
    </div>
  );
}
