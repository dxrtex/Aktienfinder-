/* Kairo – Start-Animation. Läuft beim Laden der App; der Übergang startet erst, wenn
   (a) die Animation durch ist UND (b) die App KairoSplash.ready() gemeldet hat – spätestens nach 6 s. */
(function () {
  const LOGO = `
    <div class="sp-stage">
      <div class="sp-box">
        <div class="sp-hole"></div>
        <div class="sp-logo">
          <svg viewBox="0 0 512 512" aria-hidden="true">
            <defs><radialGradient id="spGlow"><stop offset="0" stop-color="#0A84FF" stop-opacity=".55"/><stop offset="1" stop-color="#0A84FF" stop-opacity="0"/></radialGradient></defs>
            <circle class="sp-glow" cx="169" cy="256" r="150" fill="url(#spGlow)"/>
            <rect class="sp-wick" x="161" y="128" width="16" height="256" rx="8" fill="#0A84FF"/>
            <rect class="sp-body" x="137" y="186" width="64" height="140" rx="10" fill="#0A84FF"/>
            <path class="sp-chev" d="M354 150 L252 256 L354 362" fill="none" stroke="#fff" stroke-width="46" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <div class="sp-shine"></div>
        </div>
      </div>
      <div class="sp-word">${[..."KAIRO"].map(c => `<span>${c}</span>`).join("")}</div>
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
