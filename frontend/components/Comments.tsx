"use client";

import { useEffect, useState } from "react";
import Giscus from "@giscus/react";

export default function Comments() {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    // Read initial theme from localStorage
    const stored = localStorage.getItem("theme") as "light" | "dark" | null;
    const initialTheme = stored || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    setTheme(initialTheme);

    // Listen for theme changes
    const handleStorageChange = () => {
      const current = localStorage.getItem("theme") as "light" | "dark" | null;
      if (current) {
        setTheme(current);
        // Sync theme with giscus iframe
        const iframe = document.querySelector('iframe.giscus-frame') as HTMLIFrameElement | null;
        iframe?.contentWindow?.postMessage(
          { giscus: { setConfig: { theme: current } } },
          'https://giscus.app'
        );
      }
    };

    window.addEventListener('storage', handleStorageChange);
    
    // Also listen for custom event from ThemeToggle
    const handleThemeChange = (e: CustomEvent) => {
      const newTheme = e.detail as "light" | "dark";
      setTheme(newTheme);
      const iframe = document.querySelector('iframe.giscus-frame') as HTMLIFrameElement | null;
      iframe?.contentWindow?.postMessage(
        { giscus: { setConfig: { theme: newTheme } } },
        'https://giscus.app'
      );
    };

    window.addEventListener('themeChange', handleThemeChange as EventListener);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener('themeChange', handleThemeChange as EventListener);
    };
  }, []);

  return (
    <div className="mt-8">
      <Giscus
        repo="Sohan2005/the-problem-network-comments"
        repoId="R_kgDOURuIRw"
        category="Brief Comments"
        categoryId="DIC_kwDOURuIR84DFGk4"
        mapping="pathname"
        strict="0"
        reactionsEnabled="1"
        emitMetadata="0"
        inputPosition="top"
        theme={theme}
        lang="en"
        loading="lazy"
      />
      <p className="text-small text-text-muted mt-4">
        Comments require a GitHub account — this is a platform limitation of GitHub Discussions, not something we control.
      </p>
    </div>
  );
}
