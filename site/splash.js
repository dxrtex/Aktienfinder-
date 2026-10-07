/* Kairo – Start-Animation. Läuft beim Laden der App; der Übergang startet erst, wenn
   (a) die Animation durch ist UND (b) die App KairoSplash.ready() gemeldet hat – spätestens nach 6 s. */
(function () {
  const LOGO = `
    <div class="sp-stage">
      <div class="sp-box">
        <div class="sp-hole"></div>
        <div class="sp-logo">
          <svg viewBox="0 0 512 512" aria-hidden="true">
            <defs><radialGradient id="spGlow"><stop offset="0" stop-color="#30D158" stop-opacity=".5"/><stop offset="1" stop-color="#30D158" stop-opacity="0"/></radialGradient></defs>
            <ellipse class="sp-glow" cx="257.5" cy="256.0" rx="90" ry="150" fill="url(#spGlow)"/>
            <path class="sp-letters" d="M19 168.5H46.5V242.2L81.5 168.5H109L76.2 232.8L109.5 343.5H80.8L57.5 265.5L46.5 287.8V343.5H19Z M143.8 168.5H181L209.5 343.5H182L177 308.8V309.2H145.8L140.8 343.5H115.2ZM173.8 285.5 161.5 199H161L149 285.5Z M312.8 168.5H353.5Q374.8 168.5 384.5 178.4Q394.2 188.2 394.2 208.8V219.5Q394.2 246.8 376.2 254V254.5Q386.2 257.5 390.4 266.8Q394.5 276 394.5 291.5V322.2Q394.5 329.8 395 334.4Q395.5 339 397.5 343.5H369.5Q368 339.2 367.5 335.5Q367 331.8 367 322V290Q367 278 363.1 273.2Q359.2 268.5 349.8 268.5H340.2V343.5H312.8ZM350.2 243.5Q358.5 243.5 362.6 239.2Q366.8 235 366.8 225V211.5Q366.8 202 363.4 197.8Q360 193.5 352.8 193.5H340.2V243.5Z M411.5 302V210Q411.5 189 422.2 177.5Q433 166 453.2 166Q473.5 166 484.2 177.5Q495 189 495 210V302Q495 323 484.2 334.5Q473.5 346 453.2 346Q433 346 422.2 334.5Q411.5 323 411.5 302ZM467.5 303.8V208.2Q467.5 191 453.2 191Q439 191 439 208.2V303.8Q439 321 453.2 321Q467.5 321 467.5 303.8Z" fill="#fff"/>
            <g class="sp-body"><clipPath id="spu"><rect width="512" height="253.5"/></clipPath><clipPath id="spd"><rect y="258.5" width="512" height="253.5"/></clipPath><g clip-path="url(#spu)" fill="#30D158"><rect x="252.5" y="134.5" width="10" height="243" rx="5"/><rect x="234.5" y="200.0" width="46" height="112.0" rx="7"/></g><g clip-path="url(#spd)" fill="#FF453A"><rect x="252.5" y="134.5" width="10" height="243" rx="5"/><rect x="234.5" y="200.0" width="46" height="112.0" rx="7"/></g></g>
          </svg>
          <div class="sp-shine"></div>
        </div>
      </div>
    </div>`;
  const ANIM_MS = 1750, EXIT_MS = 520, TIMEOUT_MS = 6000;
  let current = null;

  function play(opts = {}) {
    if (current) current.el.remove();
    const el = document.createElement("div");
    el.className = "splash"; el.setAttribute("aria-hidden", "true"); el.innerHTML = LOGO;
    const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) el.classList.add("reduce");
    document.body.appendChild(el);
    let resolveReady;
    const ready = new Promise(r => { resolveReady = r; });
    const animDone = new Promise(r => setTimeout(r, reduce ? 300 : ANIM_MS));
    animDone.then(() => el.classList.add("waiting"));               // App lädt noch → Glow pulsiert
    const handle = { el, ready: resolveReady };
    current = handle;
    Promise.race([Promise.all([animDone, ready]), new Promise(r => setTimeout(r, TIMEOUT_MS))]).then(() => {
      el.classList.add("exit");
      setTimeout(() => { el.remove(); if (current === handle) current = null; opts.onDone && opts.onDone(); }, reduce ? 260 : EXIT_MS);
    });
    if (opts.readyAfter != null) setTimeout(resolveReady, opts.readyAfter);
    return handle;
  }

  window.KairoSplash = { play, ready() { if (current) current.ready(); } };
  // In der App automatisch starten (Vorschau-Seite startet selbst)
  if (document.currentScript && document.currentScript.dataset.autoplay !== undefined) play();
})();
