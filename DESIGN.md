# Interface design

The supplied workflow is the visual authority: URL input first, then media cards with quality controls and live progress. This is an Operate surface. Secondary Downloads navigation preserves access to active jobs after another scan.

Use an understated local utility aesthetic: warm paper surfaces, dark olive text, lime primary actions, generous workspace spacing, compact secondary information. A stacked product wordmark anchors a single header. The large two-line heading leads directly to the input. Empty states explain the next action without fabricated videos or counts.

## Tokens
- Font: locally hosted Manrope variable, 400–800, with system fallback.
- Background: #f5f5f0; surface: #ffffff; alternate: #eeefe8.
- Text: #262b22; muted: #62685b; line: #dddfd5.
- Accent: #d9f36b; accent text: #29351a; focus: #557600; error: #a42e32.
- Dark: background #191d17, surface #23281f, alternate #2c3327, text #edf0e6, muted #b2baa7, line #3b4434.
- Cards: 14px radius, single border. Buttons: 8px radius, minimum 44px height.
- Grid: three columns on large screens, two below 1000px, one below 650px.

## Behavior
Light is the initial theme; theme preference persists locally. Loading skeletons occupy the results grid. Protected videos have explanatory copy and no download action. Completed jobs expose Save file. User-selected quality persists per card. Full URL and long titles wrap or truncate without horizontal overflow. Reduced motion removes animations and transitions. SVG icons share a 1.65 stroke. Remote thumbnails are fetched by the guarded backend, never loaded directly from remote origins by the browser.

Browser and screenshot verification was unavailable in the build sandbox; this document records implemented decisions, not a visual QA result.

## Advanced browser extension

Preserve the existing theme and normal scan workflow. An Advanced mode checkbox changes the URL form action to View. Result cards also expose View page. A native modal dialog supplies focus containment and Escape-to-close for the compact browser task. The address bar, approved-tab strip, periodically refreshed interactive preview, and scroll/focus controls remain in the same surface language. Pending-tab decisions sit directly below the preview, with Stay and Go to new tab actions. The preview height is bounded so the decision area stays visible on common desktop screens. Detected media reuses the existing MediaCard and job controls inside the dialog, with notifications rendered in the dialog's top layer. Missing optional dependencies show actionable install commands. Mobile layout stacks the popup decision controls and keeps the address input shrinkable.

Navigation consent is explicit: pending proposals appear below the preview, show hostname plus URL, and distinguish Open a new tab? from Leave this page?. Stay here is always available. The secondary action is Go to new tab or Continue. Approved tabs remain distinct from proposals; proposals never enter the tab strip before approval.
