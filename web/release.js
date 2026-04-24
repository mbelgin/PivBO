/* ==========================================================================
   PivBO release info: auto-fills version + download links from the GitHub
   Releases API so the site never needs a manual bump on each release.
   This mirrors the in-app pattern where pivbo/__init__.py is the single
   source of truth and /api/version exposes it to the UI. For a static site
   the equivalent source of truth is the GitHub release tag itself.

   Populates:
     [data-pivbo-version]            → textContent becomes "v1.2.3"
     [data-pivbo-dl="windows"]       → href to the *-windows.zip asset
     [data-pivbo-dl="macos"]         → href to the *-macos.zip asset
     [data-pivbo-dl="linux"]         → href to the *.AppImage asset
     [data-pivbo-dl="page"]          → href kept on the /releases/latest page
     [data-pivbo-asset-name="win…"]  → textContent becomes the asset filename
     [data-pivbo-asset-size="win…"]  → textContent becomes a human size string
     #site-version                   → textContent becomes "PivBO v1.2.3"

   Fallback: if the API is unreachable or an asset is missing, the element
   is left pointing at the /releases/latest page and its display is
   collapsed so we never show a broken "#" link.
   ========================================================================== */
(function () {
  'use strict';

  var REPO = 'mbelgin/PivBO';
  var API = 'https://api.github.com/repos/' + REPO + '/releases/latest';
  var RELEASES_PAGE = 'https://github.com/' + REPO + '/releases/latest';
  var CACHE_KEY = 'pivbo-release-cache-v1';
  var CACHE_TTL_MS = 10 * 60 * 1000;

  var ASSET_MATCHERS = {
    windows: function (name) { return /windows.*\.zip$/i.test(name) || /\.msi$/i.test(name); },
    macos:   function (name) { return /mac(os)?.*\.zip$/i.test(name) || /\.dmg$/i.test(name); },
    linux:   function (name) { return /\.AppImage$/i.test(name); }
  };

  function readCache() {
    try {
      var raw = localStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed.at !== 'number') return null;
      if (Date.now() - parsed.at > CACHE_TTL_MS) return null;
      return parsed.data || null;
    } catch (e) {
      return null;
    }
  }

  function writeCache(data) {
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), data: data }));
    } catch (e) { /* quota, private mode. Harmless. */ }
  }

  function pickAsset(assets, platform) {
    if (!Array.isArray(assets)) return null;
    var matcher = ASSET_MATCHERS[platform];
    if (!matcher) return null;
    for (var i = 0; i < assets.length; i++) {
      var a = assets[i];
      if (a && a.name && matcher(a.name)) return a;
    }
    return null;
  }

  function apply(release) {
    if (!release) return applyFallback();

    var tag = (release.tag_name || '').replace(/^v/, '');
    var versionLabel = tag ? 'v' + tag : '';

    var versionEls = document.querySelectorAll('[data-pivbo-version]');
    for (var i = 0; i < versionEls.length; i++) {
      versionEls[i].textContent = versionLabel || 'latest';
    }

    var footer = document.getElementById('site-version');
    if (footer) {
      footer.textContent = versionLabel ? 'PivBO ' + versionLabel : 'PivBO';
    }

    var dlEls = document.querySelectorAll('[data-pivbo-dl]');
    for (var j = 0; j < dlEls.length; j++) {
      var el = dlEls[j];
      var kind = el.getAttribute('data-pivbo-dl');
      if (kind === 'page') {
        el.href = release.html_url || RELEASES_PAGE;
        continue;
      }
      var asset = pickAsset(release.assets, kind);
      if (asset && asset.browser_download_url) {
        el.href = asset.browser_download_url;
        el.removeAttribute('hidden');
      } else {
        el.href = release.html_url || RELEASES_PAGE;
        el.setAttribute('data-pivbo-dl-fallback', '1');
      }
    }

    var nameEls = document.querySelectorAll('[data-pivbo-asset-name]');
    for (var k = 0; k < nameEls.length; k++) {
      var nEl = nameEls[k];
      var nAsset = pickAsset(release.assets, nEl.getAttribute('data-pivbo-asset-name'));
      if (nAsset && nAsset.name) nEl.textContent = nAsset.name;
    }

    var sizeEls = document.querySelectorAll('[data-pivbo-asset-size]');
    for (var m = 0; m < sizeEls.length; m++) {
      var sEl = sizeEls[m];
      var sAsset = pickAsset(release.assets, sEl.getAttribute('data-pivbo-asset-size'));
      if (sAsset && typeof sAsset.size === 'number') sEl.textContent = humanSize(sAsset.size);
    }
  }

  function humanSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function applyFallback() {
    var footer = document.getElementById('site-version');
    if (footer) footer.textContent = 'PivBO';
    var dlEls = document.querySelectorAll('[data-pivbo-dl]');
    for (var i = 0; i < dlEls.length; i++) {
      if (!dlEls[i].getAttribute('href') || dlEls[i].getAttribute('href') === '#') {
        dlEls[i].href = RELEASES_PAGE;
      }
    }
  }

  function load() {
    var cached = readCache();
    if (cached) {
      apply(cached);
      return;
    }
    if (typeof fetch !== 'function') {
      applyFallback();
      return;
    }
    fetch(API, { headers: { 'Accept': 'application/vnd.github+json' } })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        writeCache(data);
        apply(data);
      })
      .catch(function () { applyFallback(); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
