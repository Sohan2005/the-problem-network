import Navbar from "@/components/Navbar";

const linkClass = "text-accent hover:text-accent-hover transition-colors";

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <main className="max-w-[720px] mx-auto px-4 py-6">
        <h1 className="text-h1 font-bold text-text mb-6">Privacy</h1>

        <div className="space-y-6">
          <section>
            <h2 className="text-h2 font-bold text-text mb-3">In Short</h2>
            <p className="text-body text-text leading-body">
              This site sets no cookies and runs no analytics, advertising or tracking scripts. Fonts are served from this site, not from Google. The only things kept about visits are anonymous daily totals.
            </p>
          </section>

          <section id="visits">
            <h2 className="text-h2 font-bold text-text mb-3">Visit Counter</h2>
            <p className="text-body text-text leading-body mb-3">
              What is counted: one visit per browser session, added to a single number for the current day (UTC). The database stores only that number for each day; the total shown in the header is the sum of those numbers.
            </p>
            <p className="text-body text-text leading-body mb-3">
              What is not counted or stored: no IP address, browser or device details, location, pages viewed, referrer or visitor identifier is saved with a visit. Unique visitors are not counted. Search engine crawlers, link previews, automated browsers and prefetch requests are not counted.
            </p>
            <p className="text-body text-text leading-body">
              To count a visit only once, your browser keeps a flag named <code>tpn-visit-counted</code> in sessionStorage. It holds no identifier, is never sent to the server, and is deleted when you close the tab.
            </p>
          </section>

          <section>
            <h2 className="text-h2 font-bold text-text mb-3">IP Addresses</h2>
            <p className="text-body text-text leading-body mb-3">
              Your IP address is used only for rate limiting, which stops one address from sending too many requests. It is used only in memory and only as a salted hash, and it is never stored by the application.
            </p>
            <p className="text-body text-text leading-body">
              The hosting platform may keep its own standard request logs outside the application&apos;s control.
            </p>
          </section>

          <section>
            <h2 className="text-h2 font-bold text-text mb-3">Stored in Your Browser</h2>
            <p className="text-body text-text leading-body mb-3">
              This site uses your browser&apos;s localStorage, which stays on your device:
            </p>
            <ul className="list-disc pl-6 space-y-2 text-body text-text leading-body mb-3">
              <li><code>theme</code>: your light or dark mode choice.</li>
              <li><code>tpn-sidebar-collapsed</code>: whether you hid the category sidebar.</li>
              <li><code>favoriteBriefs</code>: the ids of the postings you saved. When you open Saved Postings, those ids are sent to the API to load the postings; they are not stored on the server.</li>
              <li><code>giscus-session</code>: only if you sign in to comment (see below).</li>
            </ul>
            <p className="text-body text-text leading-body">
              Clearing your browser data removes all of these. Saved postings do not follow you to other devices.
            </p>
          </section>

          <section>
            <h2 className="text-h2 font-bold text-text mb-3">Comments</h2>
            <p className="text-body text-text leading-body mb-3">
              Comments use Giscus, a comment system built on GitHub Discussions. Nothing is loaded from GitHub or Giscus until you click &quot;Show comments&quot; on a posting.
            </p>
            <p className="text-body text-text leading-body mb-3">
              After that click, your browser loads the widget from giscus.app, and GitHub and Giscus receive your IP address and browser information under their own privacy policies. To post, you sign in with GitHub; Giscus then keeps its session token in this site&apos;s localStorage as <code>giscus-session</code>. This site never sees or stores that token or your GitHub details.
            </p>
            <p className="text-body text-text leading-body">
              Comments are public and stored as GitHub Discussions in the <a href="https://github.com/Sohan2005/the-problem-network-comments" target="_blank" rel="noopener noreferrer" className={linkClass}>Sohan2005/the-problem-network-comments</a> repository under the &quot;Brief Comments&quot; category, not in this site&apos;s database.
            </p>
          </section>

          <section>
            <h2 className="text-h2 font-bold text-text mb-3">Contact</h2>
            <p className="text-body text-text leading-body">
              If you have questions about this privacy policy or how your data is handled, please open an issue on the <a href="https://github.com/Sohan2005/the-problem-network" target="_blank" rel="noopener noreferrer" className={linkClass}>main project repository</a>.
            </p>
          </section>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-bg-alt py-6 mt-8">
        <div className="max-w-7xl mx-auto px-4 text-center text-text-muted text-sm">
          <p className="mb-2">The Problem Network — Translating real-world technical problems into junior-dev-friendly postings</p>
          <p>No cookies: visits are counted only as an anonymous daily total.</p>
        </div>
      </footer>
    </div>
  );
}
