/* Kairo – Start-Animation (≈ 2,2 s) nach dem finalen Markenauftritt: K-Symbol in der Kachel + Wortmarke KA|RO.
   Ablauf: Graphit-Licht und Kachel blenden auf · der Docht zieht sich aus der Mitte auf · der Körper der Kerze federt auf,
   blaues Leuchten · der Winkel des K fährt aus der Kerze heraus · die Kachel gleitet nach links, KA|RO steigt Buchstabe
   für Buchstabe aus der Grundlinie, die Kerze der Wortmarke wächst · „Der richtige Moment“ läuft zusammen · Lichtreflex.
   Übergang: Kachel öffnet sich zur App (Maske). Startet erst, wenn die Animation durch ist UND die App
   KairoSplash.ready() gemeldet hat – spätestens nach 6 s. */
(function () {
  const L = {"K": "M257.3 420.6V340.7H279.51V377.75L316.83 340.7H344.57L311.56 373.48L345.27 420.6H318.35L295.67 387.68L279.51 401.58V420.6Z", "R": "M502.3 420.6V340.7H558.36Q567.18 340.7 573 344.15Q578.82 347.61 581.74 353.39Q584.66 359.17 584.66 366.2Q584.66 373.86 581.09 379.96Q577.51 386.06 570.7 389.53L586.9 420.6H562.01L548.72 393.21H524.51V420.6ZM524.51 376.78H552.57Q556.85 376.78 559.41 374.08Q561.98 371.37 561.98 366.81Q561.98 363.83 560.83 361.72Q559.68 359.62 557.59 358.48Q555.49 357.34 552.57 357.34H524.51Z", "O": "M642.2 422Q627.68 422 617.14 417.26Q606.61 412.52 600.95 403.29Q595.3 394.06 595.3 380.66Q595.3 367.15 600.95 357.95Q606.61 348.75 617.14 344.02Q627.68 339.3 642.2 339.3Q656.88 339.3 667.37 344.02Q677.87 348.75 683.52 357.95Q689.18 367.15 689.18 380.66Q689.18 394.06 683.52 403.29Q677.87 412.52 667.37 417.26Q656.88 422 642.2 422ZM642.22 405.12Q647.85 405.12 652.32 403.59Q656.79 402.07 659.94 399.16Q663.09 396.26 664.75 392.07Q666.4 387.88 666.4 382.63V378.61Q666.4 373.35 664.75 369.17Q663.09 364.99 659.94 362.1Q656.79 359.21 652.32 357.69Q647.85 356.18 642.22 356.18Q636.6 356.18 632.13 357.69Q627.66 359.21 624.52 362.1Q621.38 364.99 619.76 369.17Q618.13 373.35 618.13 378.61V382.63Q618.13 387.88 619.76 392.07Q621.38 396.26 624.52 399.16Q627.66 402.07 632.13 403.59Q636.6 405.12 642.22 405.12Z", "A": "M341.11 420.6 375.59 340.7H401.19L435.7 420.6H411.83L406.46 407.24H369.28L363.94 420.6ZM375.73 390.82H400.02L393.53 374.28Q393.07 373.08 392.36 371.14Q391.65 369.2 390.9 366.97Q390.15 364.75 389.46 362.68Q388.77 360.61 388.32 359.29H387.51Q386.8 361.46 385.81 364.26Q384.83 367.06 383.89 369.75Q382.94 372.44 382.21 374.3Z"};
  const LOGO = `
    <div class="sp-ambient"></div>
    <div class="sp-stage">
      <div class="sp-lock">
        <div class="sp-box">
          <div class="sp-hole"></div>
          <div class="sp-tile">
            <svg viewBox="0 0 1000 1000" aria-hidden="true">
              <defs>
                <linearGradient id="spW" x1="0" y1="215" x2="0" y2="785" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#64B1FF"/><stop offset="1" stop-color="#0A84FF"/></linearGradient>
                <linearGradient id="spB" x1="0" y1="321" x2="0" y2="679" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#62B0FF"/><stop offset="1" stop-color="#0A84FF"/></linearGradient>
                <filter id="spF" x="-1" y="-1" width="3" height="3"><feGaussianBlur stdDeviation="22"/></filter>
              </defs>
              <rect class="sp-glow" x="276.6" y="321" width="93" height="358" rx="17" fill="#0A84FF" filter="url(#spF)"/>
              <rect class="sp-wick" x="313.8" y="215" width="19" height="570" rx="9.5" fill="url(#spW)"/>
              <rect class="sp-body" x="276.6" y="321" width="93" height="358" rx="17" fill="url(#spB)"/>
              <clipPath id="spCC"><rect x="380" y="270" width="0" height="460"><animate attributeName="width" values="0;360" keyTimes="0;1" calcMode="spline" keySplines=".2 .8 .2 1" begin="0.74s" dur="0.52s" fill="freeze"/></rect></clipPath>
              <g clip-path="url(#spCC)" class="sp-chevw"><path class="sp-chev" d="M612.2 281.5H722.8L504.4 500L722.8 718.5H612.2L393.8 500Z" fill="#F4F6FA"/></g>
            </svg>
            <div class="sp-shine"></div>
          </div>
        </div>
        <div class="sp-word">
          <svg viewBox="255 327 436 110" aria-hidden="true">
            <path class="sp-l sp-l1" d="${L.K}"/><path class="sp-l sp-l2" d="${L.A}"/>
            <g class="sp-wc"><rect x="462.35" y="329.3" width="4.7" height="105.7" rx="2.35"/><rect x="451.6" y="352" width="25.8" height="60.3" rx="3.5"/></g>
            <path class="sp-l sp-l3" d="${L.R}"/><path class="sp-l sp-l4" d="${L.O}"/>
          </svg>
        </div>
      </div>
      <div class="sp-tag">Der richtige Moment</div>
    </div>`;
  const ANIM_MS = 2250, EXIT_MS = 600, TIMEOUT_MS = 6000;
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
    animDone.then(() => el.classList.add("waiting"));               // App lädt noch → Leuchten pulsiert
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
  if (document.currentScript && document.currentScript.dataset.autoplay !== undefined) play();
})();
