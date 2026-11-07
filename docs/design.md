# Design notes

The design rules for The Problem Network. Every color, space, size and duration in the app comes from a token listed here.

## Principles

- Good design stays out of the way. This is a tool for developers, so it favors clear type, dense information and predictable layouts.
- If a value is missing here, add it here first, then use it.

## Color

- Warm olive palette with parchment backgrounds, olive text and one accent.
- Light: background `#fdfdf8`, alternate `#eeefe9`, text `#4d4f46`, muted text `#65675e`, border `#bfc1b7`.
- Dark: background `#1a1b18`, alternate `#252622`, text `#e8e9e6`, border `#3d3e3a`.
- Accent: `#1e1f23` for buttons, links, selected states and focus rings. Hover text uses orange `#F54E00` and nothing else does.
- Semantic colors (success, error, warning) appear only when they mean it.
- Every text and background pair meets WCAG AA contrast.

## Spacing and layout

- 8px grid: 8, 16, 24, 32, 48 and 64.
- Reading containers are at most 720px wide.
- Breakpoints: mobile to 767px (one column), tablet 768 to 1023px, desktop 1024 to 1439px, wide from 1440px.
- The navigation collapses into a mobile menu below 768px.

## Type

- IBM Plex Sans for headings and body. Weights 400, 500, 700 and 800.
- Sizes: body 16px (14px on mobile), small 14px, h3 20px, h2 28px, h1 40px. Body line height is 1.71.
- Text is left-aligned, never justified.

## Shape and motion

- Radius 4, 8 or 12px. Light card shadows, used only to show elevation.
- Motion only shows a change of state: 150ms hover, 200ms dropdown, 250ms modal, never over 300ms.
- The "live" dot pulses for 2 seconds and is static when the visitor prefers reduced motion.

## Interaction and components

- Click targets are at least 48 by 48px. Every control has hover, focus and active states.
- Icon-only buttons have an `aria-label`. The active navigation page is highlighted.
- Buttons: primary, secondary, ghost, danger. Cards: default and elevated. Inputs: default and error. Badges: default, success, warning, error.

## Pages

- **Browse:** navbar, search, filters, sort, grid, Load more, footer.
- **Posting:** navbar, title and favorite button, difficulty, problem overview, what you will build, recommended stack, getting started, learning outcomes, original source, tags, comments, footer.
- **Saved:** navbar, "Saved Postings" heading, grid, Load more, empty state, footer.
- Navigation: Browse and Saved.
- Loading: skeleton placeholders that match the final layout.

## Load more

- 24 postings per page. "Load more" adds the next page below the cards. There are no page numbers.
- A count line ("Showing 24 of 174 postings") is announced politely to screen readers.
- The button is disabled and reads "Loading..." while loading. On failure a short message appears and the cards stay.
- Changing the search, a filter or the sort goes back to the first page.

## Header strip

- Order: "Live" chip, total chip ("174 postings"), "Updated" chip, then the line "New postings added every day".
- No weekly count.

## Wording

- Visitors always see "posting", never "brief". Code, the database and the API routes still use "brief".
- Empty and error states say what happened and offer one next step. Examples: "Couldn't load this posting - check your connection and try again". Never "Something went wrong" or a raw error code.
- Required empty states: no search results, nothing saved, no postings, loading, API unavailable, connection lost, first visit.
