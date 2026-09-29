// Display diagnostics (About → "Display diagnostics"): what the phone reports about the
// screen, for layout bugs that only show on a phone (e.g. in an iPhone's home-screen app).

const OPEN_KEY = "sb.diagnostics";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // private browsing: for this page only
  }
}

/** The screen's height in CSS pixels, for the current orientation (iOS gives portrait values). */
function screenHeight(): number {
  const { width, height } = window.screen;
  const landscape = window.matchMedia?.("(orientation: landscape)").matches ?? false;
  return landscape ? Math.min(width, height) : Math.max(width, height);
}

/** For the green line: the screen's height. */
export function applyScreenHeight(): void {
  document.documentElement.style.setProperty("--screen-height", `${screenHeight()}px`);
}

export function diagnosticsOpen(): boolean {
  return read(OPEN_KEY) === "1";
}

export function setDiagnosticsOpen(open: boolean): void {
  write(OPEN_KEY, open ? "1" : null);
  window.dispatchEvent(new Event("sb-diagnostics"));
}

/** Measures a CSS length (e.g. "100lvh", "env(safe-area-inset-top)") in pixels. */
function measure(length: string): number {
  const probe = document.createElement("div");
  probe.style.cssText = `position:fixed;top:0;left:0;width:0;visibility:hidden;height:${length}`;
  document.body.appendChild(probe);
  const value = probe.getBoundingClientRect().height;
  probe.remove();
  return Math.round(value * 10) / 10;
}

function rect(selector: string): string {
  const element = document.querySelector(selector);
  if (!element) return "none";
  const box = element.getBoundingClientRect();
  return `top ${Math.round(box.top)}, bottom ${Math.round(box.bottom)}, height ${Math.round(box.height)}`;
}

/** Everything worth knowing, as label → value lines. */
export function report(): [string, string][] {
  const nav = navigator as Navigator & { standalone?: boolean };
  const viewport = window.visualViewport;
  const ios = /OS (\d+[_\d]*) like Mac OS X/.exec(navigator.userAgent)?.[1]?.replace(/_/g, ".");
  return [
    ["iOS", ios ?? "no"],
    ["Home-screen app", `${window.matchMedia?.("(display-mode: standalone)").matches} (navigator.standalone ${nav.standalone ?? "-"})`],
    ["Orientation", `${window.screen.orientation?.angle ?? (window as Window & { orientation?: number }).orientation ?? "?"}°`],
    ["Screen", `${window.screen.width} x ${window.screen.height} (avail ${window.screen.availWidth} x ${window.screen.availHeight}), dpr ${window.devicePixelRatio}`],
    ["Window inner", `${window.innerWidth} x ${window.innerHeight}`],
    ["Window outer", `${window.outerWidth} x ${window.outerHeight}`],
    ["html clientHeight", String(document.documentElement.clientHeight)],
    ["visualViewport", viewport ? `${Math.round(viewport.width)} x ${Math.round(viewport.height)}, offsetTop ${viewport.offsetTop}, pageTop ${viewport.pageTop}, scale ${viewport.scale}` : "none"],
    ["100vh / svh / lvh / dvh", ["100vh", "100svh", "100lvh", "100dvh"].map(measure).join(" / ")],
    ["100% (html)", String(Math.round(document.documentElement.getBoundingClientRect().height))],
    ["body", rect("body")],
    [
      "Safe insets t / r / b / l",
      ["top", "right", "bottom", "left"].map((side) => measure(`env(safe-area-inset-${side}, 0px)`)).join(" / "),
    ],
    ["data-notch", document.documentElement.dataset.notch ?? "-"],
    [".app", rect(".app")],
    [".player", rect(".player")],
    [".now-playing", rect(".now-playing")],
    ["Scroll", `window ${Math.round(window.scrollY)}, html ${document.documentElement.scrollTop}, body ${document.body.scrollTop}`],
    ["User agent", navigator.userAgent],
  ];
}
