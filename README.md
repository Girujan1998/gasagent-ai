# GasAgent.ai

Cross-platform mobile app (React Native, iOS + Android) backed by a FastAPI
service. Search a city, postal code, or your current GPS location to find
the 10 nearest gas stations — brand, regular/premium prices (with time since
last updated), distance, and star rating — via the
[py-gasbuddy](https://pypi.org/project/py-gasbuddy/) library.

## Structure

```
GasAgent.ai/
  mobile/    React Native (TypeScript) app — targets iOS and Android
  backend/   FastAPI service — hosts the API layer for the mobile app
```

## Backend (`backend/`)

```
backend/
  app/
    main.py                      FastAPI app + router registration
    config.py                    Settings (env-driven)
    api/routes/health.py         GET /api/v1/health
    api/routes/stations.py       GET /api/v1/stations/search
    services/gasbuddy_client.py  Wraps py-gasbuddy; maps its results to our schema
    services/geocoding.py        City/postal code -> lat/lon (Open-Meteo, free, no key)
    models/schemas.py            Pydantic request/response models
  tests/
  requirements.txt
  .env.example
```

Run it:

```bash
cd backend
python3.11 -m venv .venv   # see the Python-version note below
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload   # add --port 8001 etc. if 8000 is already taken locally
```

Verify: `curl http://127.0.0.1:8000/api/v1/health`

Run tests: `pytest`

### Station search — `GET /api/v1/stations/search`

Query params: `query` (city name or postal code) **or** `lat`+`lon`, plus
optional `limit` (default 10, max 20) and `cursor` (see Pagination below).
Returns up to `limit` stations sorted by distance, each with `brand`,
`brand_logo_url`, `connected_brand`, `connected_brand_logo_url`, `address`,
`latitude`/`longitude`, `distance_miles`, `regular` / `midgrade` /
`premium` / `diesel` (each `{price, formatted_price, last_updated}`),
`star_rating`, and `ratings_count`.

**Multi-brand stations** (`brand` vs. `connected_brand`): GasBuddy
sometimes lists more than one brand for a single station — e.g. Circle K
bought Esso's Canadian retail network, so a station can be a Circle
K-branded store selling Esso fuel, with `brands: [{name: "Circle K",
brandingType: "cstore"}, {name: "Esso", brandingType: "fuel"}]` and
`name: "Esso"`. `_select_brands()` in `gasbuddy_client.py` picks whichever
listed brand's `name` matches the station's own top-level `name` field as
`brand` (falling back to the first listed brand if none match — e.g. the
name is a street address); any other brand becomes `connected_brand`. So
for the example above, the response is `brand: "Esso"` (correct — that's
what the pumps actually say) with `connected_brand: "Circle K"` riding
along as secondary info, not `brand: "Circle K"` (the old behavior, which
just took `brands[0]` unconditionally and got it backwards for this case).
Verified against a real station: 100 Jamieson Pkwy, Cambridge, ON.

**Duplicate brand entries are treated as no connected brand.** GasBuddy's
data isn't always a genuine multi-brand list — some stations list the same
brand twice (identical name, logo, everything), not a real second brand.
`_select_brands()` skips any candidate whose `name` matches the primary's
(case-insensitively), so `connected_brand` stays `null` rather than
showing a redundant "with Esso" on an Esso station. Verified against a
real station that surfaced this exact bug: 684 Hespeler Rd, Cambridge,
ON — `brands` was `[{name: "Esso", ...}, {name: "Esso", ...}]`.

**Pagination:** the response also includes `next_cursor` (`null` once
there are no more results), and `lat`/`lon` — the coordinates actually
searched (post-geocoding, if `query` was used). To fetch the next page,
call again with `cursor=<next_cursor>` and `lat`/`lon` set to the *previous
response's* `lat`/`lon` — not the original `query` — since GasBuddy's
`price_lookup_service` requires coordinates (or a zip) on every call
regardless of cursor, and re-sending `query` would mean re-geocoding (an
extra network call, and not guaranteed to resolve identically twice).

**Implementation notes:**

- **py-gasbuddy declares `requires-python = ">=3.13"`, but nothing in its
  source actually needs 3.13-only syntax** (checked — no PEP 695 `type`
  statements, no `except*`). It's installed here on Python 3.11 via
  `pip install --ignore-requires-python py-gasbuddy` (already reflected in
  `requirements.txt`/venv setup above). A from-source Homebrew build of
  Python 3.13 was attempted first and produced a binary that gets SIGKILLed
  on launch on this machine for reasons that didn't show up in any system
  log — abandoned in favor of the pip override, which works cleanly.
- **No API key needed.** py-gasbuddy fetches a CSRF token from
  gasbuddy.com and calls its public GraphQL endpoint directly. Confirmed
  working live (not Cloudflare-blocked) from this machine as of
  2026-08-14; if GasBuddy tightens bot protection later, py-gasbuddy
  supports routing through a FlareSolverr instance (`solver_url` param) —
  not wired up here since it wasn't needed.
- **`query` is always geocoded to lat/lon first** (rather than passing a
  zip code straight through to py-gasbuddy's `zipcode` param), because
  GasBuddy's own zipcode search doesn't return a `distance` for results,
  and distance is a required field here. Trade-off: postal codes resolve
  to a centroid, not an exact address — see the precision note below.
- **Canadian postal codes** (`M5V 3L9`, `m5v3l9`, ...) are detected via
  `services/geocoding.py`'s `CA_POSTAL_CODE_PATTERN` and geocoded through
  [Zippopotam.us](https://www.zippopotam.us/) (`GET
  api.zippopotam.us/CA/{FSA}`) instead of Open-Meteo, which doesn't
  support them at all (confirmed: querying it with a Canadian postal code
  returns zero results). Zippopotam only resolves the first 3 characters
  (the FSA, e.g. `M5V`) — the full 6-character code isn't geocodable via
  this free lookup, so it's neighborhood-level precision, same idea as the
  US zip → city-centroid trade-off below.
- Everything else (city names, US zip codes) still goes through
  Open-Meteo's free geocoding API. Trade-off there: postal codes resolve
  to their city's centroid, not zip-level precision. Good enough for a
  first pass; swap in a dedicated postal-code-centroid dataset or a keyed
  geocoder later if precision matters.

## Mobile app (`mobile/`)

**App display name is "GasAgent.ai"** (`app.json`'s `displayName`, iOS
`CFBundleDisplayName`, Android `strings.xml`'s `app_name`, and the in-app
title text) — this is what users see. The underlying project identifiers
(`GasAIAgentMobile` npm package name, Xcode project/scheme, Android
package `com.gasaiagentmobile`, the `mobile/` folder itself) are
deliberately **not** renamed to match: doing so means new bundle IDs,
re-signing, moving native source directories to match a new package
structure, and re-registering the Xcode project — a much bigger, riskier
change than "update the app's name" implies. Say the word if you want that
deeper rename too.

Standard React Native TypeScript project (`react-native init`, pinned to **0.73.9**
— see note below), plus:

```
mobile/
  App.tsx                            Wraps everything in FavoritesProvider; owns active-tab state
  src/
    api/client.ts                    fetch wrapper for the backend's /api/v1 routes (health, station search)
    navigation/BottomNavBar.tsx      5-tab bottom bar (Home/Search/Chat/Favorites/Personal) with a raised center Chat button
    screens/HomeScreen.tsx           Search bar + station results list (the "Home" tab)
    screens/FavoritesScreen.tsx      Favorited stations + the location-share banner (the "Favorites" tab)
    screens/PlaceholderScreen.tsx    "Coming soon" screen used for Search/Chat/Personal
    components/LocationSearchBar.tsx Top search bar: city/postal code text, or current GPS location
    components/StationList.tsx       Loading/error/empty states + the results FlatList + detail modal state
    components/StationCard.tsx       One station, tappable: logo, brand, distance, prices, rating, favorite star
    components/StationDetailModal.tsx Bottom-sheet popup: full station details + "Navigate" button
    store/FavoritesContext.tsx       AsyncStorage-backed favorites list, shared via React context
    utils/time.ts                    "Xm/Xh/Xd ago" formatting for price last_updated timestamps
    utils/distance.ts                Haversine distance (favorites) + miles->km conversion (detail modal)
    utils/location.ts                Shared Android location-permission request (used by search + favorites)
    utils/maps.ts                    Opens the device's default maps app with directions to a station
```

Tab switching is plain local state in `App.tsx` (no routing library yet) —
`BottomNavBar` is a presentational component that takes `activeTab` +
`onTabPress`. "Home" and "Favorites" have real content; "Search"/"Chat"/
"Personal" render `PlaceholderScreen`. Swap in `@react-navigation` later if
the app grows past simple tab-swapping (e.g. needs per-tab history/deep
linking).

**Search results — and the search bar itself — survive switching tabs
(pagination doesn't).** Because tabs are conditionally rendered,
`HomeScreen` fully unmounts when you leave it — so its `useState` alone
would lose the search on every tab switch. `App.tsx` now owns a
`PersistedSearch` (the original `LocationQuery`, resolved lat/lon, first
page of results, first-page cursor) above `HomeScreen`, passed down as
props and written back via `onSearchComplete` only when a *new* search
completes — never from "load more". `HomeScreen` seeds its local state
from those props on mount, and passes the persisted query down to
`LocationSearchBar` as `initialQuery` so the input text (or the "Using
location: lat, lon" label, for a GPS search) comes back too — not just the
results list. Leave Home after scrolling through 3 pages, come back, and
you see the first page again immediately (no refetch), search box and all
— exactly the "persist the search, not the pagination" behavior asked for.
Covered by a test in `HomeScreen.test.tsx` that searches, loads a second
page, unmounts, remounts with the captured persisted state, and asserts
zero new station-search network calls, only the first page showing, and
the search bar's text matching what was searched.

**Clearing the search bar:** `LocationSearchBar` shows a ✕ button whenever
there's a query or location label to clear (typed text, or a persisted/
just-used GPS search) — tapping it resets the bar to blank so the next
thing typed is unambiguously a new search, without touching the results
still on screen until that new search actually completes.

**Brand logo fallback:** `StationCard`'s `BrandLogo` shows a ⛽ icon (not
initials) for stations with no `brand_logo_url` or a broken image URL —
this is common for smaller/independent stations, which GasBuddy often has
no brand image for at all (e.g. an empty `brands` list). Confirmed against
a real one ("PS Fuels" near Elgin, IL).

**Connected brand:** when a station has a `connected_brand` (see the
backend section above), both `StationCard` and `StationDetailModal` show
it as a small italic line — "*with Circle K*", its own tiny logo if
available — directly under the primary brand name, never styled as if it
were co-equal with the primary. Same component in both places, so search
results and Favorites render it identically.

**Station detail popup:** tapping a `StationCard` (in search results *or*
Favorites — same component, same behavior) opens `StationDetailModal` as a
bottom-sheet popup (React Native's built-in `Modal`, `transparent` +
`animationType="slide"`) rather than navigating to a new screen — there's
no navigation library in this app, and a modal is the simpler, correct fit
here anyway. It shows the brand logo, name, address, distance, all four
fuel grades (regular/midgrade/premium/diesel, added to the backend schema
for this — previously only regular/premium were exposed), star rating, and
a "Navigate" button. The ✕ close button lives in `StationCard`'s top-right
corner of the sheet. The favorite star inside `StationCard` still works
normally when the card is tappable — nested `TouchableOpacity` correctly
claims its own touch in React Native, so starring a card never also opens
the modal.

**Distance is shown in kilometers, everywhere** — both the compact
`StationCard` badge (search results and Favorites) and the expanded
`StationDetailModal`. The backend's `distance_miles` field name stays as
is (that's the unit GasBuddy itself reports, and it's also what
`FavoritesScreen`'s Haversine recompute produces — see below), and
`utils/distance.ts`'s `milesToKm()` converts it at render time in both
components — a display-only conversion, not a data model change.

The Navigate button's icon (`StationDetailModal`'s `NavigateIcon`) is a
small hand-built circle-and-arrow — a cyan circle, white ring border, white
triangular arrow rotated 45° via the classic RN "CSS-triangle" trick
(transparent side borders + one colored border edge) — matching a
reference image the user supplied, without pulling in an SVG/icon library
for one glyph.

**Time-since-updated granularity:** `utils/time.ts`'s `timeAgo()` now shows
minutes alongside hours once there's more than an hour of leftover minutes
— `"2h 15m ago"` rather than rounding down to `"2h ago"` — for anything
under 24 hours old. Exact-hour timestamps (e.g. precisely 120 minutes) still
show as just `"2h ago"`, no `"2h 0m"`. Shared by both `StationCard`'s
compact price row and `StationDetailModal`'s expanded one, so both stay
consistent automatically.

`utils/maps.ts`'s `openDirections()` opens the device's default maps app:
`maps:0,0?q=<label>@<lat>,<lng>` on iOS, `geo:0,0?q=<lat>,<lng>(<label>)`
on Android, falling back to a `google.com/maps` web URL if the native
scheme fails to open (e.g. no maps app registered) or on any other
platform. Not tested by actually tapping the button in the Simulator —
this environment can't simulate real touch gestures — so it's verified
with a test asserting `Linking.openURL` is called with a URL containing
the station's coordinates. Worth an actual on-device tap-through before
shipping, since the exact scheme behavior (does it fall through to Apple
Maps correctly, etc.) is the one thing a mocked `Linking` call can't
confirm.

**Bottom nav dead zones (fixed):** tapping a tab worked inconsistently
depending on exactly where on it you tapped. Two compounding causes, both
classic RN gotchas invisible in a screenshot:
1. `bar` used `alignItems: 'center'`, which shrinks each tab's
   `TouchableOpacity` down to hug its icon+label content instead of
   filling the bar's height — so the touchable area was a narrow strip in
   the middle of each tab, not the full visual button. Changed to
   `alignItems: 'stretch'`.
2. The "Chat" label under the center button is `position: 'absolute'`
   with `left: 0, right: 0` so it can `textAlign: 'center'` — which also
   makes its (invisible) layout box span the *entire bar width* at label
   height, sitting on top of Search/Favorites in z-order. Native hit
   testing picks whatever view's frame contains the touch point first,
   regardless of whether that view actually handles touches — so taps
   landing in that band were swallowed by inert text instead of reaching
   the tab underneath. Fixed with `pointerEvents: 'none'` on that label.

`LocationSearchBar` captures a text query or the device's current coordinates
(via `@react-native-community/geolocation`) and calls `onSearch`.
`HomeScreen` sends that straight to `searchNearestStations()` in
`api/client.ts`, which hits the backend's `/stations/search` and renders the
results through `StationList`/`StationCard`.

**Infinite scroll:** `StationList` wires `FlatList`'s `onEndReached` (fired
at `onEndReachedThreshold={0.5}`, i.e. half a screen from the bottom) to
`HomeScreen.handleLoadMore`, which fetches the next 10 stations using the
cursor and coordinates from the previous response and appends them to the
list, showing a small spinner as a `ListFooterComponent` while it loads.
`HomeScreen` tracks the in-flight/cursor state in refs rather than state —
`onEndReached` needs to read the *latest* cursor synchronously (it can fire
again before a state update from the previous page has re-rendered), so a
plain `loadingMore` boolean in state alone isn't enough to prevent duplicate
in-flight requests; the ref is checked and set before state's setter fires.
A failed "load more" request stops pagination quietly rather than surfacing
an error — the stations already on screen stay valid either way.

**Note:** the search request's query string is built by hand in
`client.ts` rather than with `URLSearchParams` — Hermes's polyfill doesn't
implement `.set()`, which was caught by testing the actual search flow live
in the Simulator (not by `tsc`/`eslint`/`jest`, which all happily passed
with the broken version).

### Favorites

Every `StationCard` — in search results *and* on the Favorites tab, since
it's the same component — has a star button (☆ / ★) that calls
`toggleFavorite()` from `FavoritesContext`. Favorites are stored as full
`GasStation` snapshots (whatever the search returned at the moment of
favoriting — brand, prices, rating, etc.) in AsyncStorage under the key
`gasaiagent:favorites`, loaded once on app start and persisted on every
change. Tapping the star again — in either screen — removes it.

**Distance on the Favorites tab is intentionally not the `distance_miles`
stored in that snapshot.** A favorited station's stored distance was
relative to whatever location was searched *when it was favorited* —
showing it later, from wherever the user actually is now, would just be
wrong. So `FavoritesScreen` always overrides `distance_miles` to `null`
unless the user has shared their current location in that screen, in which
case it recomputes distance client-side with a Haversine formula
(`utils/distance.ts`) from each station's `latitude`/`longitude` (added to
the backend's `GasStation` schema for exactly this) to the freshly-fetched
current position. Sharing location is a tap on a banner shown whenever it
isn't yet available, reusing the same Android permission flow as the
"use current location" button in search (`utils/location.ts`).

The AI chat UI (previously a floating bubble) was removed pending a redesign
of how the app talks to the AI agent. The bottom nav bar's "Chat" tab
currently just opens the placeholder screen — nothing chat-related is wired
in yet.

`src/api/client.ts` points at `http://localhost:8001` (`10.0.2.2` on the Android
emulator). Update `API_BASE_URL` to match whatever port the backend is actually
running on, or a deployed backend's address.

Run it (with the backend already running):

```bash
cd mobile
npm install

# Android (Android SDK required, emulator running or device connected)
npm run android

# iOS (requires Xcode; see version note below)
bundle install
bundle exec pod install
npm run ios
```

### Why @react-native-async-storage/async-storage is pinned to 1.24.0

The latest major (3.x) is a Swift rewrite that fails `pod install` on this
project's Podfile (`static library` linking, no `use_modular_headers!`) with
"Swift pod `AsyncStorage` ... cannot yet be integrated as static libraries."
1.24.0 is the last pre-Swift release and links cleanly. Also needed for
Jest: `jest.config.js` maps the real module to the library's official mock
(`@react-native-async-storage/async-storage/jest/async-storage-mock`) via
`moduleNameMapper` — that mock file is meant to be wired up that way (or via
an explicit `jest.mock(...)` call), not dropped into `setupFiles` directly,
which was tried first and silently did nothing.

### Why React Native is pinned to 0.73.9, not the latest

This machine has Xcode 13.4.1, and Xcode 14.3 itself requires macOS 13
(Ventura) or later to even install — this Mac is on macOS 12.7.2 (Monterey).
React Native 0.74+ hard-fails `pod install` below Xcode 14.3. 0.73.9 has no
such gate and was confirmed to build and run correctly here. If you later
update macOS + Xcode, you can bump `react-native` (and matching
`@react-native/*` packages) to 0.74+ following the [upgrade helper](https://react-native-community.github.io/upgrade-helper/).

### Other environment gaps on this machine

- **Android Studio's bundled JRE is Java 11; the Android Gradle plugin needs
  Java 17.** `brew install openjdk@17` and either export
  `JAVA_HOME=$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home`
  before building, or set `org.gradle.java.home` in
  `mobile/android/gradle.properties`.
- Node is v18.16.0 — works fine for RN 0.73's tooling.
- Metro's own terminal auto-launch doesn't work in a non-interactive shell.
  Start it yourself first (`npx react-native start &`), then run
  `npx react-native run-ios --no-packager` / `run-android`.
- Port 8000 may already be in use by unrelated local projects on this
  machine — the backend was run on 8001 during verification; adjust
  `API_BASE_URL` in `mobile/src/api/client.ts` to match.

### Verified during scaffolding

- Backend: dependencies install, `pytest` passes, `/health` and
  `/stations/search` respond correctly over live HTTP — including real
  live calls to GasBuddy for a city name, a US postal code, and lat/lon,
  all returning real current prices/ratings.
- Mobile: `tsc --noEmit`, `eslint`, `jest`, a release Metro bundle, and
  Android `gradlew assembleDebug` all pass.
- **iOS: built and launched in the Simulator (iPhone 13, iOS 15.5).**
  Confirmed on-screen end-to-end: the health check, and a live station
  search (city name) rendering real GasBuddy results — brand, address,
  distance, regular/premium prices with "time ago", and star ratings —
  through the actual backend. This run is also what caught the
  `URLSearchParams.set()` gap noted above.
