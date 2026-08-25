/**
 * Bird Calendar — orchestrator.
 *
 * Geolocation → current BirdNET week → one 48-week prediction at the point
 * (BirdNET Geomodel via ONNX worker) → rank the species we have plates for:
 *   Mode A (Residents): size ∝ this week's occurrence probability; sitting plates.
 *   Mode B (Migration): size ∝ arrival score (P[next]−P[prev])/peak; flying plates.
 * Birds are scattered around an empty centre; hover shows the name (language
 * selectable); 👍/👎 sends feedback via EmailJS.
 */
(function () {
  var MODEL_URL = "geomodel_fp16.onnx";
  var LABELS_URL = "labels.txt";
  var TAX_URL = "taxonomy.csv";
  var MANIFEST_URL = "birds/manifest.json";
  var PLATES_URL = "plates/manifest.json";
  // Species the app has no image for at all (scripts/build_missing.py). They are
  // drawn as placeholders so a bird that is genuinely present here isn't simply
  // absent from the calendar, and so images can be requested for it.
  var MISSING_URL = "missing.json";
  var DEFAULT = { lat: 59.33, lon: 18.07, name: "Stockholm (default)" }; // fallback

  var LANG_NAMES = {
    en: "English", sv: "Svenska", de: "Deutsch", fr: "Français", es: "Español",
    nl: "Nederlands", fi: "Suomi", no: "Norsk", da: "Dansk", it: "Italiano",
    pt: "Português", pl: "Polski", ru: "Русский", ja: "日本語", "zh-CN": "中文",
    cs: "Čeština", uk: "Українська", tr: "Türkçe",
  };

  // Localised page title (falls back to English for any other locale).
  var TITLES = {
    en: "Birds here today", sv: "Fåglar här idag", de: "Vögel heute hier",
    fr: "Oiseaux ici aujourd'hui", es: "Aves aquí hoy", nl: "Vogels hier vandaag",
    fi: "Linnut täällä tänään", no: "Fugler her i dag", da: "Fugle her i dag",
    it: "Uccelli qui oggi", pt: "Aves aqui hoje", pl: "Ptaki tutaj dzisiaj",
    ru: "Птицы здесь сегодня", ja: "今日ここの鳥", "zh-CN": "此地今日鸟类",
    cs: "Ptáci tady dnes", uk: "Птахи тут сьогодні", tr: "Bugün buradaki kuşlar",
  };

  // Per-language name casing: eBird already follows each language's convention
  // (Swedish/Finnish/Polish/Czech lowercase; German/French/Danish capitalised),
  // except Norwegian, which it stores lowercase though the Norwegian birding
  // convention capitalises species names ("svarttrost" -> "Svarttrost").
  var CAP_FIRST = { no: 1 };

  // Human-readable source for the image-origin line in the hover tooltip.
  var BOOK_INFO = {
    gould: "John Gould, The Birds of Europe",
    dresser: "H. E. Dresser, A History of the Birds of Europe",
    vonwright: "M. & W. von Wright, Svenska fåglar",
    lilford: "Lord Lilford, Coloured Figures of the Birds of the British Islands (Thorburn & Keulemans)",
  };
  // Book sources in default preference order; short labels for the detail view.
  var BOOKS = ["gould", "dresser", "vonwright", "lilford"];
  var BOOK_LABEL = { gould: "Gould", dresser: "Dresser", vonwright: "von Wright", lilford: "Lilford" };

  var S = {
    labels: [], codeToIdx: {}, nSpecies: 0,
    tax: {}, langs: [], lang: "en",
    manifest: {}, plates: {}, missing: {}, probs: {},  // probs: {weekIndex: Float32Array(nSpecies)}
    fieldId: null,                         // field_id.json, fetched on first detail view
    lat: DEFAULT.lat, lon: DEFAULT.lon, week: 1, mode: "A", src: "gould",
    aiBW: false,
  };

  // Images the user downvoted this session — grayed out until the tab closes.
  var DOWNVOTED = (function () {
    try { return new Set(JSON.parse(sessionStorage.getItem("bc_down") || "[]")); }
    catch (e) { return new Set(); }
  })();
  function markDownvoted(img) {
    DOWNVOTED.add(img);
    try { sessionStorage.setItem("bc_down", JSON.stringify([...DOWNVOTED])); }
    catch (e) {}
  }

  // ---- Worker / inference ---------------------------------------------------
  var worker = new Worker("inference-worker.js");
  var pending = {}, nextId = 1, workerReady = null;

  function initWorker() {
    workerReady = new Promise(function (resolve, reject) {
      worker.onmessage = function (e) {
        var m = e.data;
        if (m.type === "init") { m.ok ? resolve() : reject(new Error(m.error)); return; }
        if (m.type === "infer") {
          var cb = pending[m.id]; delete pending[m.id];
          if (!cb) return;
          if (m.error) cb.reject(new Error(m.error));
          else cb.resolve(new Float32Array(m.data));
        }
      };
      worker.postMessage({ type: "init", modelUrl: MODEL_URL });
    });
    return workerReady;
  }

  function runInference(flatInputs, batchSize) {
    return new Promise(function (resolve, reject) {
      var id = nextId++;
      pending[id] = { resolve: resolve, reject: reject };
      var buf = flatInputs.buffer;
      worker.postMessage({ type: "infer", id: id, flatInputs: buf,
        batchSize: batchSize, task: "raw" }, [buf]);
    });
  }

  // ---- Data loading ---------------------------------------------------------
  function loadLabels(text) {
    S.labels = text.trim().split("\n").map(function (line, i) {
      var p = line.split("\t");
      return { code: p[0], sci: p[1] || "", common: p[2] || p[1] || "", idx: i };
    });
    S.nSpecies = S.labels.length;
    S.labels.forEach(function (l) { S.codeToIdx[l.code] = l.idx; });
  }

  function parseCsv(text) {
    var rows = [], row = [], f = "", q = false;
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; }
        else f += c;
      } else if (c === '"') q = true;
      else if (c === ",") { row.push(f); f = ""; }
      else if (c === "\n") { row.push(f); f = ""; rows.push(row); row = []; }
      else if (c !== "\r") f += c;
    }
    if (f.length || row.length) { row.push(f); rows.push(row); }
    return rows;
  }

  function loadTaxonomy(text, needed) {
    var rows = parseCsv(text);
    var h = rows[0];
    var codeCol = h.indexOf("species_code"), sciCol = h.indexOf("sci_name");
    var enCol = h.indexOf("com_name");
    var langCol = { en: enCol };
    S.langs = ["en"];
    for (var c = 0; c < h.length; c++) {
      var m = /^common_name_(.+)$/.exec(h[c]);
      if (m) { langCol[m[1]] = c; S.langs.push(m[1]); }
    }
    for (var r = 1; r < rows.length; r++) {
      var code = rows[r][codeCol];
      if (!code || !needed[code]) continue;
      var rec = { sci: rows[r][sciCol] || "", names: {} };
      for (var lg in langCol) {
        var v = rows[r][langCol[lg]];
        if (v) rec.names[lg] = v;
      }
      S.tax[code] = rec;
    }
  }

  // Preferred path: names embedded in the manifest (lets us skip the 10 MB
  // taxonomy.csv download — important for free GitHub Pages bandwidth).
  function useManifestNames() {
    var has = false;
    for (var c in S.manifest) { if (S.manifest[c].names) { has = true; break; } }
    if (!has) return false;
    var langset = {};
    for (var code in S.manifest) {
      var e = S.manifest[code];
      S.tax[code] = { sci: e.sci || "", names: e.names || {} };
      for (var lg in (e.names || {})) langset[lg] = 1;
    }
    S.langs = Object.keys(langset);
    if (S.langs.indexOf("en") < 0) S.langs.unshift("en");
    return true;
  }

  // Plate-only species aren't in the AI manifest's names; pull their localized
  // names (embedded in plates/manifest.json) into S.tax so the caption is in
  // the chosen locale for every bird.
  function mergePlateNames() {
    var langset = {};
    // Species with no image at all carry their own names too, so a placeholder
    // is labelled in the chosen language.
    [S.plates, S.missing].forEach(function (src) {
      for (var code in src) {
        var e = src[code];
        if (!S.tax[code] && (e.names || e.sci)) {
          S.tax[code] = { sci: e.sci || "", names: e.names || {} };
        }
        for (var lg in (e.names || {})) langset[lg] = 1;
      }
    });
    for (var l2 in langset) {
      if (S.langs.indexOf(l2) < 0) S.langs.push(l2);
    }
  }

  // Open the image review tool for a species. A species that has no images at
  // all isn't in the review manifest, so it is passed as a request (with its
  // name, which that page can't look up) and the tool offers to add images.
  function openReview(code) {
    var url = "review.html#" + encodeURIComponent(code);
    if (S.missing[code]) {
      var nm = nameFor(code);
      url = "review.html?add=" + encodeURIComponent(code) +
        "&name=" + encodeURIComponent(nm.common) +
        "&sci=" + encodeURIComponent(nm.sci || "");
    }
    window.open(url, "_blank", "noopener");
  }

  function nameFor(code) {
    var rec = S.tax[code];
    var common = (rec && (rec.names[S.lang] || rec.names.en)) ||
      (S.manifest[code] && S.manifest[code].common) || code;
    if (CAP_FIRST[S.lang] && common) {
      common = common.charAt(0).toUpperCase() + common.slice(1);
    }
    var sci = (rec && rec.sci) || (S.manifest[code] && S.manifest[code].sci) || "";
    return { common: common, sci: sci };
  }

  // ---- Metrics --------------------------------------------------------------
  function birdNetWeek(d) {
    var start = new Date(d.getFullYear(), 0, 0);
    var day = Math.floor((d - start) / 86400000);
    return Math.max(1, Math.min(48, Math.floor((day - 1) / 365 * 48) + 1));
  }

  // Weeks the current mode needs: Residents only needs this week's occurrence;
  // Migration needs the neighbouring weeks too, to measure the rising trend.
  function neededWeeks() {
    var wi = S.week - 1;
    return S.mode === "A" ? [wi] : [(wi + 47) % 48, wi, (wi + 1) % 48];
  }

  function metrics(code) {
    var idx = S.codeToIdx[code];
    if (idx === undefined) return null;
    var wi = S.week - 1;
    var cur = S.probs[wi] ? S.probs[wi][idx] : 0;
    if (S.mode === "A") return { cur: cur, arrival: 0 };
    // Migration: rising sharpness from prev->next, normalised by the local
    // window (we no longer run all 48 weeks just to get the annual peak).
    var pw = S.probs[(wi + 47) % 48], nw = S.probs[(wi + 1) % 48];
    var prev = pw ? pw[idx] : cur, next = nw ? nw[idx] : cur;
    var norm = Math.max(cur, prev, next, 1e-6);
    return { cur: cur, arrival: (next - prev) / norm };
  }

  // ---- Rendering ------------------------------------------------------------
  var stage = document.getElementById("stage");
  var tip = document.getElementById("tip");

  function pickImage(entry, stance) {
    var list = (entry.stances && entry.stances[stance]) || [];
    return list.length ? list[Math.floor(Math.random() * list.length)] : null;
  }

  // Pick the image to show for a species given the chosen source.
  //  - "ai": the generated stance cutout (flippable to face centre).
  //  - a book in BOOKS: the public-domain book plate; the chosen book is
  //    preferred, the other is the fallback, and species with no plate fall
  //    back to the AI cutout so the page stays full. Plates carry their own
  //    labels, so they are never flipped.
  // Returns {src, id, flip} or null. `id` keys downvotes and the faces map.
  function chooseImage(code, stance) {
    function ai() {
      var img = pickImage(S.manifest[code] || {}, stance);
      if (!img) return null;
      var face = ((S.manifest[code] || {}).faces || {})[img];
      return { src: "birds/" + img, id: img, flip: true, face: face, ai: true,
        origin: "AI-generated field-guide illustration", page: null };
    }
    if (S.src === "ai") return ai();
    var p = S.plates[code];
    if (p) {
      var order = [S.src].concat(BOOKS.filter(function (b) { return b !== S.src; }));
      // Prefer a single-species plate (from either book, in source order); only
      // fall back to a multi-species plate — which shows the whole plate, other
      // species included — when no clean single one exists for this species.
      var single = null, sBook = null, whole = null, wBook = null;
      for (var i = 0; i < order.length; i++) {
        var b = order[i], e = p[b];
        if (!e) continue;
        if (e.multi) { if (!whole) { whole = e; wBook = b; } }
        else { single = e; sBook = b; break; }
      }
      var pick = single || whole, book = single ? sBook : wBook;
      if (pick) {
        var origin = (BOOK_INFO[book] || book) +
          (pick.volume ? ", " + pick.volume : "") +
          (pick.multi ? " — plate shows several species" : "");
        return { src: pick.img, id: pick.img, flip: true, face: pick.face,
          origin: origin, page: pick.page_url || null };
      }
    }
    return ai();   // no plate for this species: fall back to an AI image
  }

  // Stand-in for a species with no image in any source — the bird still belongs
  // on the page, and the card links into the review tool to ask for images.
  function placeholderFor(code) {
    if (!S.missing[code] && S.manifest[code]) return null;   // has images, just not this stance
    return { src: null, id: "missing/" + code, missing: true, flip: false,
      origin: "No image yet — add one in the image review tool", page: null };
  }

  function render() {
    stage.innerHTML = "";
    var stance = S.mode === "A" ? "sitting" : "flying";
    var items = [];
    // Union of AI-manifest and plate codes: a plate-covered species may not
    // have an AI image yet, and vice versa.
    var codes = {};
    Object.keys(S.manifest).forEach(function (c) { codes[c] = 1; });
    if (S.src !== "ai") Object.keys(S.plates).forEach(function (c) { codes[c] = 1; });
    Object.keys(S.missing).forEach(function (c) { codes[c] = 1; });
    Object.keys(codes).forEach(function (code) {
      var pick = chooseImage(code, stance) || placeholderFor(code);
      if (!pick) return;
      var mt = metrics(code);
      if (mt && mt.cur <= 0.01) return;   // only species with >1% occurrence here
      var value = !mt ? 0.5 : (S.mode === "A" ? mt.cur : Math.max(0, mt.arrival));
      if (S.mode === "B" && mt && mt.arrival <= 0) return; // only arriving species
      if (value <= 0) return;
      items.push({ code: code, img: pick.id, src: pick.src, flip: pick.flip,
        face: pick.face, origin: pick.origin, page: pick.page, ai: pick.ai,
        missing: pick.missing, stance: stance, value: value });
    });
    document.getElementById("hint").style.display = items.length ? "none" : "flex";
    if (!items.length) {
      document.getElementById("hint").textContent =
        S.mode === "A" ? "No resident birds to show here." : "No arriving migrants this week.";
    }

    // Dense top-to-bottom packing by probability; the page scrolls. The layout
    // (just maths) is computed for all birds, but DOM elements are created
    // incrementally as the page is scrolled (see buildUpTo).
    var W = stage.clientWidth || window.innerWidth;
    var res = window.BirdLayout.placeScroll(items, W);
    stage.style.height = res.height + "px";
    SCROLL.items = res.placed.slice().sort(function (a, b) { return a.y - b.y; });
    SCROLL.idx = 0; SCROLL.halfW = W / 2;
    stage.classList.toggle("aibw", S.aiBW);   // grayscale AI images when chosen
    window.scrollTo(0, 0);
    buildUpTo(2 * window.innerHeight);   // first screenful (+ one ahead)
    setStatus(items.length);
  }

  // Incremental builder: birds are mounted only once the scroll reaches them.
  var SCROLL = { items: [], idx: 0, halfW: 0 };

  function buildBird(it) {
    var el = document.createElement("div");
    el.className = "bird" + (DOWNVOTED.has(it.img) ? " downvoted" : "") +
      (it.ai ? " ai" : "");
    el.style.left = it.x + "px"; el.style.top = it.y + "px";
    el.style.width = it.size + "px"; el.style.height = it.size + "px";

    if (it.missing) {                      // no image anywhere: draw a card
      el.className += " missing";
      var ph = document.createElement("div");
      ph.className = "ph";
      ph.title = "No image yet for " + nameFor(it.code).common;
      ph.innerHTML = '<span class="ph-glyph" aria-hidden="true">🪶</span>' +
        '<span class="ph-name"></span>' +
        '<button type="button" class="ph-add">+ add images</button>';
      ph.querySelector(".ph-name").textContent = nameFor(it.code).common;
      // The card opens the species like any other bird; only this button leaves
      // for the image tool.
      ph.querySelector(".ph-add").onclick = function (e) {
        e.stopPropagation();
        openReview(it.code);
      };
      el.appendChild(ph);
      el.addEventListener("mousemove", function (ev) { showTip(ev, it); });
      el.addEventListener("mouseleave", function () { tip.classList.remove("show"); });
      el.addEventListener("click", function () {
        tip.classList.remove("show"); openBird(it);
      });
      stage.appendChild(el);
      return;
    }

    var im = document.createElement("img");
    im.loading = "lazy"; im.decoding = "async";
    im.src = it.src; im.alt = nameFor(it.code).common;
    // Flip the bird so it faces the centre of the page (beak toward middle).
    if (it.flip && it.face) {
      if ((it.x > SCROLL.halfW && it.face === "right") ||
          (it.x < SCROLL.halfW && it.face === "left")) {
        im.style.transform = "scaleX(-1)";
      }
    }
    el.appendChild(im);

    var fb = document.createElement("div");
    fb.className = "fb";
    fb.innerHTML =
      '<button class="up" title="Good">👍</button>' +
      '<button class="down" title="Poor">👎</button>' +
      (it.ai ? '<button class="rev" title="Improve this drawing (review)">✎</button>' : '');
    fb.querySelector(".up").onclick = function (e) { e.stopPropagation(); doVote(it, "up", fb); };
    fb.querySelector(".down").onclick = function (e) { e.stopPropagation(); doVote(it, "down", fb); };
    if (it.ai) {
      fb.querySelector(".rev").onclick = function (e) {
        e.stopPropagation();
        openReview(it.code);
      };
    }
    el.appendChild(fb);

    el.addEventListener("mousemove", function (ev) { showTip(ev, it); });
    el.addEventListener("mouseleave", function () { tip.classList.remove("show"); });
    el.title = nameFor(it.code).common;
    el.addEventListener("click", function () { tip.classList.remove("show"); openBird(it); });
    stage.appendChild(el);
  }

  // Mount every not-yet-built bird whose top edge is above yLimit.
  function buildUpTo(yLimit) {
    var a = SCROLL.items;
    while (SCROLL.idx < a.length && a[SCROLL.idx].y - a[SCROLL.idx].size / 2 <= yLimit) {
      buildBird(a[SCROLL.idx]); SCROLL.idx++;
    }
  }

  var _scrollPending = false;
  function onScroll() {
    if (_scrollPending) return;
    _scrollPending = true;
    requestAnimationFrame(function () {
      _scrollPending = false;
      buildUpTo(window.scrollY + 2 * window.innerHeight);  // one screen ahead
    });
  }

  function doVote(it, dir, fb) {
    if (window.BirdFeedback) {
      var nm = nameFor(it.code);
      window.BirdFeedback.vote(it.img, dir, {
        species: it.code, common: nm.common, sci: nm.sci,
        pose: it.stance, lang: S.lang, src: S.src, url: it.src,
      });
    }
    // Not sticky: flash the clicked button, then clear it.
    var btn = fb.querySelector(dir === "up" ? ".up" : ".down");
    btn.classList.add("act");
    setTimeout(function () { btn.classList.remove("act"); }, 400);
    // Downvote grays the bird out for the rest of the session.
    if (dir === "down") {
      markDownvoted(it.img);
      if (fb.parentElement) fb.parentElement.classList.add("downvoted");
    }
  }

  function showTip(ev, it) {
    var nm = nameFor(it.code);
    var html = nm.common + (nm.sci ? '<br><span class="sci">' + nm.sci + "</span>" : "");
    var meta = [];
    if (it.origin) meta.push("<b>Image:</b> " + it.origin);
    var mt = metrics(it.code);
    if (mt) {
      var pct = Math.round(Math.max(0, Math.min(1, mt.cur)) * 100);
      meta.push("<b>Seen here this week:</b> " + pct + "%");
    }
    if (meta.length) html += '<div class="meta">' + meta.join("<br>") + "</div>";
    html += '<div class="hint2">Click for photos &amp; sounds (Macaulay Library)</div>';
    tip.innerHTML = html;
    tip.style.left = ev.clientX + "px";
    tip.style.top = (ev.clientY + 18) + "px";
    tip.classList.add("show");
  }

  function setStatus(n) {
    var modeName = S.mode === "A" ? "Residents" : "Migration";
    document.getElementById("status").textContent =
      modeName + " · week " + S.week + " of 48 · " + n + " species";
  }

  // ---- Controls -------------------------------------------------------------
  function setupControls() {
    document.querySelectorAll("#mode button").forEach(function (b) {
      b.onclick = async function () {
        document.querySelectorAll("#mode button").forEach(function (x) { x.classList.remove("on"); });
        b.classList.add("on"); S.mode = b.getAttribute("data-mode");
        setStatus("…");
        await ensureProbs();   // Migration needs neighbouring weeks; compute if missing
        render();
      };
    });
    document.querySelectorAll("#src button").forEach(function (b) {
      b.onclick = function () {
        document.querySelectorAll("#src button").forEach(function (x) { x.classList.remove("on"); });
        b.classList.add("on"); S.src = b.getAttribute("data-src"); render();
      };
    });
    var sel = document.getElementById("lang");
    // Only offer languages we have a friendly name for, plus English first.
    var offer = S.langs.filter(function (l) { return LANG_NAMES[l]; });
    if (offer.indexOf("en") < 0) offer.unshift("en");
    sel.innerHTML = offer.map(function (l) {
      return '<option value="' + l + '">' + (LANG_NAMES[l] || l) + "</option>";
    }).join("");
    var def = "en";   // default to English
    S.lang = def; sel.value = def; setTitle();
    sel.onchange = function () { S.lang = sel.value; setTitle(); render(); };
    // AI images colour vs black & white — toggled live without a rebuild.
    document.querySelectorAll("#aimode button").forEach(function (b) {
      b.onclick = function () {
        document.querySelectorAll("#aimode button").forEach(function (x) { x.classList.remove("on"); });
        b.classList.add("on");
        S.aiBW = b.getAttribute("data-aimode") === "bw";
        stage.classList.toggle("aibw", S.aiBW);
      };
    });
    // Only reflow when the WIDTH changes — height-only resizes (mobile address
    // bar showing/hiding while scrolling) must not reshuffle the layout.
    var lastW = window.innerWidth;
    window.addEventListener("resize", debounce(function () {
      if (window.innerWidth === lastW) return;
      lastW = window.innerWidth; render();
    }, 200));
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  function setTitle() {
    var t = TITLES[S.lang] || TITLES.en;
    document.getElementById("title").textContent = t;
    document.title = S.place ? (t + " — " + S.place) : t;
  }

  function setupHelp() {
    var modal = document.getElementById("help-modal");
    document.getElementById("help-btn").onclick = function () { modal.hidden = false; };
    document.getElementById("help-close").onclick = function () { modal.hidden = true; };
    modal.addEventListener("click", function (e) {
      if (e.target.id === "help-modal") modal.hidden = true;
    });
  }

  // Full-screen detail view for a clicked bird. The image cycles through the
  // available sources (Gould, Dresser, von Wright, AI) when clicked; a book source links
  // straight to the scanned page.
  var BIRD = { code: null, variants: [], idx: 0 };

  // ---- Identification text -------------------------------------------------
  // field_id.json carries a sourced description per species (Wikipedia, CC
  // BY-SA, cross-referenced between three language editions — see
  // scripts/fetch_field_id.py). It is shown in an editable box under the large
  // image; edits stay in this browser and can be exported as field_id_edits.json
  // for scripts/apply_field_id_edits.py to fold back into the dataset.
  var FIELDID_URL = "field_id.json";
  var DESC_KEY = "birdcal.desc.edits";
  var descEdits = {};
  try { descEdits = JSON.parse(localStorage.getItem(DESC_KEY) || "{}"); } catch (e) {}

  function saveDescEdits() {
    try { localStorage.setItem(DESC_KEY, JSON.stringify(descEdits)); } catch (e) {}
  }

  function descEntry(code) { return (S.fieldId && S.fieldId[code]) || null; }

  // ~600 kB, and only needed once a bird is opened — fetched on first use.
  var _fieldIdReq = null;
  function loadFieldId() {
    if (!_fieldIdReq) {
      _fieldIdReq = fetch(FIELDID_URL)
        .then(function (r) { return r.ok ? r.json() : {}; })
        .catch(function () { return {}; })
        .then(function (j) { S.fieldId = j; return j; });
    }
    return _fieldIdReq;
  }

  function descText(code) {
    var edit = descEdits[code];
    if (edit && typeof edit.text === "string") return edit.text;
    var e = descEntry(code);
    return e ? e.text : "";
  }

  function downloadDescEdits() {
    var out = {};
    Object.keys(descEdits).forEach(function (c) {
      out[c] = { text: descEdits[c].text, ts: descEdits[c].ts,
        base_revid: descEdits[c].base_revid || null, lang: descEdits[c].lang || "" };
    });
    var blob = new Blob([JSON.stringify(out, null, 1)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "field_id_edits.json";
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  // Render the description box for the species in the open detail view.
  function showDescription(code) {
    var wrap = document.getElementById("bird-desc-wrap");
    var box = document.getElementById("bird-desc");
    var entry = descEntry(code);
    if (!entry && !descEdits[code]) { wrap.hidden = true; return; }
    wrap.hidden = false;
    box.value = descText(code);
    box.dataset.code = code;
    showDescriptionFooter(code);
  }

  // The status line and links below the box — redrawn on every edit, while the
  // textarea itself is left alone so the caret doesn't jump.
  function showDescriptionFooter(code) {
    var state = document.getElementById("bird-desc-state");
    var foot = document.getElementById("bird-desc-foot");
    var entry = descEntry(code);
    var edited = !!descEdits[code];
    state.textContent = edited ? "edited here" :
      (entry && entry.check === "conflict" ? "sources disagree on size" :
        (entry && entry.check === "ok" ? "cross-checked" : ""));
    // Field notes are line-based and long; size the box to its content (up to
    // 44% of the window) instead of leaving most of it hidden behind a scroll.
    var box2 = document.getElementById("bird-desc");
    box2.style.height = "auto";
    box2.style.height = Math.min(window.innerHeight * 0.44,
                                 box2.scrollHeight + 4) + "px";
    // ... and let the plate give up some height when there is a note to read.
    var card = document.querySelector(".bird-card");
    if (card) card.classList.toggle("has-notes", !!(entry && entry.notes));

    foot.textContent = "";
    var m = entry && entry.measures;
    if (m) {
      var bits = [];
      if (m.length) bits.push("length " + fmtRange(m.length, "cm"));
      if (m.wingspan) bits.push("wingspan " + fmtRange(m.wingspan, "cm"));
      if (m.mass) bits.push("weight " + fmtRange(m.mass, "g"));
      if (bits.length) foot.appendChild(document.createTextNode(bits.join(" · ")));
    }
    if (entry && entry.url) {
      var a = document.createElement("a");
      a.href = entry.url; a.target = "_blank"; a.rel = "noopener";
      // Field notes are compiled from every edition consulted; a plain
      // description quotes the one edition it came from.
      a.textContent = entry.notes
        ? "Compiled from Wikipedia (" + (entry.langs || ["en"]).join(", ") + "), CC BY-SA →"
        : "Source: Wikipedia (" + (entry.lang || "en") + "), CC BY-SA →";
      foot.appendChild(a);
    }
    if (edited) {
      var revert = document.createElement("button");
      revert.type = "button";
      revert.textContent = "Revert to source";
      revert.onclick = function () {
        delete descEdits[code]; saveDescEdits(); showDescription(code);
      };
      foot.appendChild(revert);
      var dl = document.createElement("button");
      dl.type = "button";
      dl.textContent = "Export all edits (" + Object.keys(descEdits).length + ")";
      dl.onclick = downloadDescEdits;
      foot.appendChild(dl);
    }
  }

  function fmtRange(r, unit) {
    var lo = Math.round(r[0] * 10) / 10, hi = Math.round(r[1] * 10) / 10;
    return (lo === hi ? lo : lo + "–" + hi) + " " + unit;
  }

  function birdVariants(code) {
    var out = [];
    var p = S.plates[code] || {};
    BOOKS.forEach(function (b) {
      var e = p[b];
      if (!e) return;
      out.push({
        label: BOOK_LABEL[b],
        src: e.img, page: e.page_url || null, ai: false,
        origin: (BOOK_INFO[b] || b) + (e.volume ? ", " + e.volume : "") +
          (e.multi ? " — plate shows several species" : ""),
      });
    });
    var m = S.manifest[code];
    if (m && m.stances) {
      var img = null;
      ["sitting", "flying"].forEach(function (s) {
        if (!img && m.stances[s] && m.stances[s].length) img = m.stances[s][0];
      });
      for (var k in m.stances) {
        if (!img && m.stances[k] && m.stances[k].length) img = m.stances[k][0];
      }
      if (img) out.push({ label: "AI", src: "birds/" + img, page: null, ai: true,
        origin: "AI-generated field-guide illustration" });
    }
    return out;
  }

  function showBirdVariant() {
    var nm = nameFor(BIRD.code);
    var v = BIRD.variants[BIRD.idx];
    var img = document.getElementById("bird-img");
    // A species with no image at all shows the placeholder panel instead.
    var noImage = !v.src;
    img.hidden = noImage;
    document.getElementById("bird-missing").hidden = !noImage;
    if (noImage) { img.removeAttribute("src"); } else { img.src = v.src; }
    img.alt = nm.common;
    img.style.filter = (v.ai && S.aiBW)
      ? "grayscale(1) sepia(.22) contrast(.62) brightness(1.12)" : "";
    img.style.cursor = BIRD.variants.length > 1 ? "pointer" : "default";
    document.getElementById("bird-name").textContent = nm.common;
    document.getElementById("bird-sci").textContent = nm.sci || "";
    showDescription(BIRD.code);

    var srcEl = document.getElementById("bird-src");
    srcEl.textContent = "Source: ";
    if (v.page) {
      var a = document.createElement("a");
      a.href = v.page; a.target = "_blank"; a.rel = "noopener";
      a.textContent = v.origin;
      srcEl.appendChild(a);
    } else {
      srcEl.appendChild(document.createTextNode(v.origin));
    }

    var extra = document.getElementById("bird-extra");
    extra.textContent = "";
    if (noImage) {
      var add = document.createElement("a");
      add.href = "#";
      add.className = "add-images";
      add.textContent = "Add images for this species →";
      add.onclick = function (e) { e.preventDefault(); openReview(BIRD.code); };
      extra.appendChild(add);
      extra.appendChild(document.createElement("br"));
    }
    if (BIRD.variants.length > 1) {
      var sources = BIRD.variants.map(function (x) { return x.label; }).join(" · ");
      extra.appendChild(document.createTextNode("Tap the image to switch source (" + sources + ")"));
      extra.appendChild(document.createElement("br"));
    }
    var mt = metrics(BIRD.code);
    if (mt) {
      var pct = Math.round(Math.max(0, Math.min(1, mt.cur)) * 100);
      extra.appendChild(document.createTextNode("Seen here this week: " + pct + "%"));
      extra.appendChild(document.createElement("br"));
    }
    var ml = document.createElement("a");
    ml.href = "https://search.macaulaylibrary.org/catalog?taxonCode=" +
      encodeURIComponent(BIRD.code) + "&mediaType=photo";
    ml.target = "_blank"; ml.rel = "noopener";
    ml.textContent = "Photos & sounds on Macaulay Library →";
    extra.appendChild(ml);
    // Link to this species' call recordings on xeno-canto.
    if (nm.sci) {
      extra.appendChild(document.createElement("br"));
      var xc = document.createElement("a");
      xc.href = "https://xeno-canto.org/species/" + nm.sci.trim().replace(/\s+/g, "-");
      xc.target = "_blank"; xc.rel = "noopener";
      xc.textContent = "Listen to its calls on xeno-canto →";
      extra.appendChild(xc);
    }
    // For AI drawings, deep-link to this species' card on the review page.
    if (v.ai) {
      extra.appendChild(document.createElement("br"));
      var rv = document.createElement("a");
      rv.href = "review.html#" + encodeURIComponent(BIRD.code);
      rv.target = "_blank"; rv.rel = "noopener";
      rv.textContent = "Improve this drawing (review) →";
      extra.appendChild(rv);
    }
  }

  function openBird(it) {
    BIRD.code = it.code;
    BIRD.variants = birdVariants(it.code);
    if (!BIRD.variants.length) {
      BIRD.variants = [{ label: "", src: it.src, page: it.page,
        origin: it.origin || "—", ai: !!it.ai }];
    }
    var at = -1;
    for (var i = 0; i < BIRD.variants.length; i++) {
      if (BIRD.variants[i].src === it.src) { at = i; break; }
    }
    BIRD.idx = at >= 0 ? at : 0;
    showBirdVariant();
    document.getElementById("bird-modal").hidden = false;
    if (!S.fieldId) {
      loadFieldId().then(function () {
        if (BIRD.code === it.code) showDescription(it.code);
      });
    }
  }

  function setupBirdModal() {
    var modal = document.getElementById("bird-modal");
    document.getElementById("bird-close").onclick = function () { modal.hidden = true; };
    document.getElementById("bird-img").addEventListener("click", function () {
      if (BIRD.variants.length > 1) {
        BIRD.idx = (BIRD.idx + 1) % BIRD.variants.length;
        showBirdVariant();
      }
    });
    // Edits are kept per species in this browser; an unchanged box stores nothing.
    var box = document.getElementById("bird-desc");
    var pending = null;
    box.addEventListener("input", function () {
      var code = box.dataset.code;
      if (!code) return;
      clearTimeout(pending);
      pending = setTimeout(function () {
        var entry = descEntry(code);
        var text = box.value;
        if (entry && text.trim() === (entry.text || "").trim()) delete descEdits[code];
        else descEdits[code] = { text: text, ts: new Date().toISOString(),
          base_revid: entry ? entry.revid : null, lang: entry ? entry.lang : "" };
        saveDescEdits();
        showDescriptionFooter(code);
      }, 400);
    });
    modal.addEventListener("click", function (e) {
      if (e.target === modal) modal.hidden = true;   // click backdrop to close
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") modal.hidden = true;
    });
  }

  // All controls live in one dropdown menu to keep the bar compact.
  function setupMenu() {
    var wrap = document.getElementById("menu-wrap");
    var btn = document.getElementById("menu-btn");
    var menu = document.getElementById("menu");
    function close() { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); }
    btn.onclick = function (e) {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
      btn.setAttribute("aria-expanded", menu.hidden ? "false" : "true");
    };
    document.addEventListener("click", function (e) {
      if (!wrap.contains(e.target)) close();
    });
    // Close after picking a view/image/location/about (language stays open).
    menu.querySelectorAll("#mode button, #src button, #place, #help-btn")
      .forEach(function (b) { b.addEventListener("click", close); });
  }

  function debounce(fn, ms) {
    var t; return function () { clearTimeout(t); t = setTimeout(fn, ms); };
  }

  // ---- Location + map -------------------------------------------------------
  // Run the geomodel only for the weeks not already computed at this location.
  async function ensureProbs() {
    var missing = neededWeeks().filter(function (w) { return !S.probs[w]; });
    if (!missing.length) return;
    var inputs = new Float32Array(missing.length * 3);
    missing.forEach(function (w, i) {
      inputs[i * 3] = S.lat; inputs[i * 3 + 1] = S.lon; inputs[i * 3 + 2] = w + 1;
    });
    var out = await runInference(inputs, missing.length);
    var n = S.nSpecies;
    missing.forEach(function (w, i) { S.probs[w] = out.subarray(i * n, (i + 1) * n); });
  }

  async function setLocation(lat, lon, name) {
    S.lat = lat; S.lon = lon;
    S.place = name || (lat.toFixed(2) + ", " + lon.toFixed(2));
    document.getElementById("place").textContent = "📍 " + S.place;
    setTitle();     // reflect the selected place in the page/tab title
    S.probs = {};   // location changed — previous weeks no longer valid
    setStatus("…");
    await ensureProbs();
    render();
  }

  var _map = null, _marker = null;
  function openMap() {
    var modal = document.getElementById("map-modal");
    modal.hidden = false;
    if (!_map) {
      _map = L.map("map").setView([S.lat, S.lon], 4);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        { maxZoom: 12, attribution: "© OpenStreetMap" }).addTo(_map);
      _marker = L.marker([S.lat, S.lon]).addTo(_map);
      _map.on("click", function (e) {
        _marker.setLatLng(e.latlng);
        modal.hidden = true;
        setLocation(e.latlng.lat, e.latlng.lng, null);
      });
    } else {
      _marker.setLatLng([S.lat, S.lon]); _map.setView([S.lat, S.lon]);
    }
    setTimeout(function () { _map.invalidateSize(); }, 60);  // size known after unhide
  }

  function setupMap() {
    document.getElementById("place").addEventListener("click", openMap);
    document.getElementById("map-close").addEventListener("click", function () {
      document.getElementById("map-modal").hidden = true;
    });
    document.getElementById("map-modal").addEventListener("click", function (e) {
      if (e.target.id === "map-modal") e.currentTarget.hidden = true;
    });
  }

  // ---- Boot -----------------------------------------------------------------
  function getLocation() {
    return new Promise(function (resolve) {
      if (!navigator.geolocation) return resolve(DEFAULT);
      navigator.geolocation.getCurrentPosition(
        function (p) { resolve({ lat: p.coords.latitude, lon: p.coords.longitude, name: null }); },
        function () { resolve(DEFAULT); },
        { timeout: 8000, maximumAge: 3600000 });
    });
  }

  async function boot() {
    try {
      var texts = await Promise.all([
        fetch(LABELS_URL).then(function (r) { return r.text(); }),
        fetch(MANIFEST_URL).then(function (r) { return r.json(); }),
        fetch(PLATES_URL).then(function (r) { return r.ok ? r.json() : {}; })
          .catch(function () { return {}; }),
        fetch(MISSING_URL).then(function (r) { return r.ok ? r.json() : {}; })
          .catch(function () { return {}; }),
        initWorker(),
      ]);
      loadLabels(texts[0]);
      S.manifest = texts[1];
      S.plates = texts[2] || {};
      S.missing = texts[3] || {};
      // Names come from the manifest when present; otherwise fall back to the
      // (large) taxonomy.csv for backward compatibility.
      if (!useManifestNames()) {
        var taxText = await fetch(TAX_URL).then(function (r) { return r.text(); });
        loadTaxonomy(taxText, S.manifest);
      }
      mergePlateNames();   // localized names for plate-only species
      setupControls();
      setupMap();
      setupHelp();
      setupMenu();
      setupBirdModal();

      S.week = birdNetWeek(new Date());
      var loc = await getLocation();
      await setLocation(loc.lat, loc.lon, loc.name);
    } catch (err) {
      console.error(err);
      document.getElementById("hint").textContent = "Failed to load: " + err.message;
    }
  }

  boot();
})();
