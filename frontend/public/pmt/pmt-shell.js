// ProjectMangoTech brand shell: one theme preference shared by the site and every app on *.projectmangotech.com,
// a slim bar at the top of each app with the way back to the main site and the light/dark switch, and the account menu
// (who is signed in, their applications and settings, sign out) in that bar and in the site's own header.
//
//   <script src="pmt/pmt-shell.js" data-app="NAS Sync Manager"></script>
//
// Attributes on the script tag: data-app (the app's name in the bar), data-home (the link back, default
// https://projectmangotech.com/), data-home-label, data-default ("dark" or "light" when nothing is stored and the
// browser has no preference), data-no-bar (apply the theme only; the page draws its own bar), data-mark (path to the
// logo mark, default pmt-mark.svg next to this script), data-account (the site's account pages: by default
// https://projectmangotech.com/account/ on the site's own hosts and /account/ on this host anywhere else; "off" leaves
// the account menu out), data-home-link="off" (no "← projectmangotech.com" text link: the logo is the way back; the
// standard application header, Core ADR-038), data-sticky="on" (the bar stays at the top of the window; its height is
// published as --mf-shell-offset on <body>, so an applet's own sticky menu sits just below it). Staging's hosts (*.projectmangotech.localhost, deploy/staging) count as the site's own, with
// http://projectmangotech.localhost/ in place of https://projectmangotech.com/.
//
// The account menu fills every element with class pmt-account (the bar has one). It asks the account service who is
// signed in (GET <account>api/me, with credentials), so a host other than the site needs that address in its
// Content-Security-Policy connect-src; without it the menu simply does not appear. The same answer says whether this
// application has a page in the help centre, and the bar then shows a Help link to it.
//
// The shared demo login, in a sandbox with more than one role, also gets "View <application> as" in its menu: the roles
// that sandbox has, the one it holds now marked; choosing one asks the account service (POST <account>api/demo-role) and
// reloads, so the application opens with that access level. The choice lasts for this sign-in only.
//
// In a sandbox the answer says so (sandbox: true), and the bar shows a quiet "Sandbox" notice in its middle, so no
// application needs its own demonstration flag.
//
// For a signed-in person the same answer carries Core home (Core ADR-026): the bar gains the application switcher (the
// applications they can open) and the bell (notifications waiting, linking to Core home), the account menu links Core
// home, and their personal settings (theme, size, reduced motion) are applied and cached per host, so the next page
// starts with them. window.pmtAppearance.apply(settings) applies settings now (Core home calls it after saving).
//
// The theme is written to <html data-theme="dark|light"> before the page renders (load this script in <head>,
// not deferred), kept in a cookie on the parent domain so subdomains share it, and mirrored in localStorage for
// hosts outside that domain. window.pmtTheme exposes get(), set(theme), toggle(); a "pmt-theme" event fires on
// window whenever it changes, including changes made in another tab.
(function () {
  'use strict';
  var root = document.documentElement;
  var script = document.currentScript || (function () { var s = document.getElementsByTagName('script'); return s[s.length - 1]; })();
  var data = (script && script.dataset) || {};
  var base = script && script.src ? script.src.replace(/[^/]*$/, '') : '';
  var COOKIE = 'pmt_theme', KEY = 'pmt-theme';
  var host = location.hostname;
  var staging = /(^|\.)projectmangotech\.localhost$/.test(host);
  var domain = /(^|\.)projectmangotech\.com$/.test(host) ? '.projectmangotech.com' : staging ? '.projectmangotech.localhost' : '';
  var SITE = staging ? 'http://projectmangotech.localhost/' : 'https://projectmangotech.com/';
  var valid = function (v) { return v === 'dark' || v === 'light'; };

  function readCookie() {
    var m = document.cookie.match(/(?:^|;\s*)pmt_theme=(dark|light)\b/);
    return m ? m[1] : '';
  }
  function readStored() {
    var v = readCookie();
    if (!v) { try { v = localStorage.getItem(KEY) || ''; } catch (e) { v = ''; } }
    return valid(v) ? v : '';
  }
  function store(theme) {
    var attrs = COOKIE + '=' + theme + '; Path=/; Max-Age=31536000; SameSite=Lax' + (domain ? '; Domain=' + domain : '') + (location.protocol === 'https:' ? '; Secure' : '');
    try { document.cookie = attrs; } catch (e) {}
    try { localStorage.setItem(KEY, theme); } catch (e) {}
  }
  function current() { return root.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; }
  function apply(theme, remember) {
    theme = valid(theme) ? theme : 'dark';
    var changed = root.getAttribute('data-theme') !== theme;
    root.setAttribute('data-theme', theme);
    root.style.colorScheme = theme;
    if (remember !== false) store(theme);
    paintToggles(theme);
    if (changed) { try { window.dispatchEvent(new CustomEvent('pmt-theme', {detail: {theme: theme}})); } catch (e) {} }
    return theme;
  }
  function initial() {
    var stored = readStored();
    if (stored) return stored;
    var pref = data.default === 'light' || data.default === 'dark' ? data.default : '';
    try {
      if (window.matchMedia('(prefers-color-scheme: light)').matches) return 'light';
      if (window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
    } catch (e) {}
    return pref || 'dark';
  }

  // ---- the toggle(s) ----
  var SUN = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  var MOON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
  function paintToggles(theme) {
    var buttons = document.querySelectorAll('.pmt-theme-toggle');
    for (var i = 0; i < buttons.length; i++) {
      var b = buttons[i], toLight = theme === 'dark';
      b.innerHTML = (toLight ? SUN : MOON) + '<span class="pmt-theme-label">' + (toLight ? 'Light' : 'Dark') + '</span>';
      b.setAttribute('aria-label', toLight ? 'Switch to light mode' : 'Switch to dark mode');
      b.setAttribute('title', toLight ? 'Switch to light mode' : 'Switch to dark mode');
      b.setAttribute('aria-pressed', String(theme === 'light'));
    }
  }
  function toggle() { var t = apply(current() === 'dark' ? 'light' : 'dark'); saveTheme(t); return t; }

  // ---- personal settings (Core home): size and reduced motion as classes on <html>, the theme as above ----
  var APPEAR = 'pmt-appearance', SIZES = {large: 'pmt-size-large', larger: 'pmt-size-larger'};
  function applyAppearance(a, keep) {
    if (!a || typeof a !== 'object') return;
    for (var k in SIZES) root.classList.toggle(SIZES[k], a.size === k);
    root.classList.toggle('pmt-reduce-motion', !!a.reduceMotion);
    if (valid(a.theme) && a.theme !== current()) apply(a.theme);
    if (keep !== false) { try { localStorage.setItem(APPEAR, JSON.stringify({theme: a.theme || '', size: a.size || 'standard', reduceMotion: !!a.reduceMotion})); } catch (e) {} }
  }
  try { var cached = JSON.parse(localStorage.getItem(APPEAR) || 'null'); if (cached) { for (var c in SIZES) root.classList.toggle(SIZES[c], cached.size === c); root.classList.toggle('pmt-reduce-motion', !!cached.reduceMotion); } } catch (e) {}
  // The bar's switch, used by someone signed in with their own account, becomes their saved theme.
  var signedIn = null;
  function saveTheme(theme) {
    if (!signedIn || signedIn.demo || !window.fetch) return;
    try { var a = JSON.parse(localStorage.getItem(APPEAR) || '{}'); a.theme = theme; localStorage.setItem(APPEAR, JSON.stringify(a)); } catch (e) {}
    fetch(ACCOUNT + 'api/appearance', {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json', 'X-Core-Request': '1'}, body: JSON.stringify({theme: theme})}).catch(function () {});
  }
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('.pmt-theme-toggle') : null;
    if (b) { e.preventDefault(); toggle(); }
  });

  // ---- the account menu ----
  var ACCOUNT = data.account === 'off' ? '' : (data.account || (domain ? SITE + 'account/' : '/account/')).replace(/\/?$/, '/');
  var CARET = '<svg class="pmt-account-caret" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
  var menus = 0;
  function accountStyles() {
    if (document.querySelector('link[data-pmt-account]')) return;
    var l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = base + 'pmt-account.css'; l.setAttribute('data-pmt-account', '');
    document.head.appendChild(l);
  }
  function roleChoices(r) {
    if (!r || !r.list || r.list.length < 2) return '';
    return '<div class="pmt-account-roles" role="group" aria-label="View ' + esc(r.name) + ' as"><span class="pmt-account-label">View ' + esc(r.name) + ' as</span>'
      + r.list.map(function (x) { return '<button type="button" class="pmt-account-role" data-app="' + esc(r.app) + '" data-role="' + esc(x.key) + '" aria-pressed="' + (x.key === r.current) + '">' + esc(x.name) + '</button>'; }).join('')
      + '</div>';
  }
  // The organisation the person works in (Core ADR-042), and the others they belong to. A sandbox page always works in
  // the demonstration organisation, so it names that one and offers no switch.
  function orgChoices(me) {
    if (!me.org) return '';
    var list = me.sandbox ? [] : (me.orgs || []);
    if (list.length < 2) return '<div class="pmt-account-org-now"><span class="pmt-account-label">Organisation</span><strong>' + esc(me.org.name) + '</strong></div>';
    return '<div class="pmt-account-roles" role="group" aria-label="Organisation"><span class="pmt-account-label">Working in</span>'
      + list.map(function (o) { return '<button type="button" class="pmt-account-role pmt-account-org" data-org="' + esc(o.id) + '" aria-pressed="' + (o.id === me.org.id) + '">' + esc(o.name) + '</button>'; }).join('')
      + '</div>';
  }
  function currentRole(me) {
    if (!me.roles) return '';
    for (var i = 0; i < me.roles.list.length; i++) if (me.roles.list[i].key === me.roles.current) return me.roles.list[i].name;
    return '';
  }
  function accountMenu(me) {
    var here = encodeURIComponent(location.href);
    if (!me.signedIn) return '<a class="pmt-account-signin" href="' + esc(me.login + '?next=' + here) + '">Sign in</a>';
    var id = 'pmt-account-menu-' + (++menus);
    var items = me.demo
      ? roleChoices(me.roles)
        + '<p class="pmt-account-note">You are using the shared demo login. Create an account of your own to use the live applications.</p>'
        + '<a href="' + esc(me.register + '?next=' + here) + '">Create your account</a>'
      : (me.core ? '<a href="' + esc(me.core) + '">Core home</a><a href="' + esc(me.core + '#waiting') + '">Waiting for you' + (me.unread ? ' (' + me.unread + ')' : '') + '</a>' : '')
        + '<a href="' + esc(me.account + '#apps') + '">My applications</a>'
        + '<a href="' + esc(me.account + '#profile') + '">Account settings</a>'
        + '<a href="' + esc(me.account + '#security') + '">Password and sign-in</a>';
    return '<button type="button" class="pmt-account-button" aria-expanded="false" aria-controls="' + id + '" aria-label="Account: ' + esc(me.name) + '">'
      + '<span class="pmt-account-initials" aria-hidden="true">' + esc(me.initials) + '</span>'
      + '<span class="pmt-account-name" aria-hidden="true">' + esc(me.demo ? 'Demo' + (currentRole(me) ? ': ' + currentRole(me) : '') : me.name.split(/\s+/)[0]) + '</span>' + CARET + '</button>'
      + '<div class="pmt-account-menu" id="' + id + '" hidden>'
      + '<div class="pmt-account-who"><strong>' + esc(me.name) + '</strong>' + (me.email ? '<span>' + esc(me.email) + '</span>' : '') + '</div>'
      + (me.demo ? '' : orgChoices(me))
      + items
      + '<button type="button" class="pmt-account-signout">Sign out</button></div>';
  }
  function accountMenus() {
    var slots = document.querySelectorAll('.pmt-account');
    if (!ACCOUNT || !slots.length || !window.fetch) return;
    accountStyles();
    fetch(ACCOUNT + 'api/me?here=' + encodeURIComponent(location.href), {credentials: 'include', cache: 'no-store'})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (me) {
        if (!me || typeof me.signedIn !== 'boolean') return;
        for (var i = 0; i < slots.length; i++) { slots[i].innerHTML = accountMenu(me); slots[i].classList.add('pmt-account-ready'); }
        if (me.signedIn) { signedIn = me; if (me.appearance) applyAppearance(me.appearance); coreControls(me); searchSetup(me); }
        var notice = document.querySelector('.pmt-bar-notice');
        if (notice && me.sandbox) { notice.hidden = false; measure(); }
        var help = document.querySelector('.pmt-bar-help');
        if (help && typeof me.help === 'string' && /^https?:\/\//.test(me.help)) { help.href = me.help; help.hidden = false; }
      })
      .catch(function () {});
  }
  // The application switcher and the bell, in the bar only (the site's own header keeps its account menu).
  var GRID = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>';
  var BELL = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>';
  function coreControls(me) {
    if (!me.core) return;
    var sw = document.querySelector('.pmt-bar .pmt-switch'), bell = document.querySelector('.pmt-bar .pmt-bell');
    if (sw && me.apps) {
      var id = 'pmt-switch-menu-' + (++menus), here = location.href;
      var list = me.apps.map(function (a) { return '<a href="' + esc(a.url) + '"' + (here.indexOf(a.url) === 0 ? ' aria-current="page"' : '') + '><span>' + esc(a.name) + '</span><small>' + (a.kind === 'live' ? 'Live' : 'Sandbox') + '</small></a>'; }).join('');
      sw.innerHTML = '<button type="button" class="pmt-account-button pmt-switch-button" aria-expanded="false" aria-controls="' + id + '" aria-label="Applications" title="Applications">' + GRID + '</button>'
        + '<div class="pmt-account-menu pmt-switch-menu" id="' + id + '" hidden><a class="pmt-switch-home" href="' + esc(me.core) + '"><span>Core home</span></a>' + (list || '<p class="pmt-account-note">No applications yet.</p>') + '</div>';
      sw.hidden = false;
    }
    if (bell) {
      bell.innerHTML = '<a class="pmt-bell-link" href="' + esc(me.core + '#waiting') + '" aria-label="' + (me.unread ? me.unread + ' waiting for you' : 'Nothing waiting for you') + '" title="Waiting for you">' + BELL + (me.unread ? '<span class="pmt-bell-count">' + (me.unread > 99 ? '99+' : me.unread) + '</span>' : '') + '</a>';
      bell.hidden = false;
    }
  }
  function setMenu(button, open) {
    var menu = document.getElementById(button.getAttribute('aria-controls'));
    if (!menu) return;
    menu.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
  }
  function closeMenus(except) {
    var open = document.querySelectorAll('.pmt-account-button[aria-expanded="true"]');
    for (var i = 0; i < open.length; i++) if (open[i] !== except) setMenu(open[i], false);
  }
  // Signing out posts to the account service (from another host of the site too) and reloads: a public page then shows
  // "Sign in", and an application's gate asks for a sign-in again.
  function signOut(button) {
    button.disabled = true;
    fetch(ACCOUNT + 'logout', {method: 'POST', credentials: 'include', redirect: 'manual', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: ''})
      .catch(function () {})
      .then(function () { location.reload(); });
  }
  document.addEventListener('click', function (e) {
    var t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    var button = t.closest('.pmt-account-button');
    if (!t.closest('.pmt-account, .pmt-switch')) closeMenus(null);
    if (button) { e.preventDefault(); closeMenus(button); setMenu(button, button.getAttribute('aria-expanded') !== 'true'); return; }
    var out = t.closest('.pmt-account-signout');
    if (out) { e.preventDefault(); signOut(out); }
    var org = t.closest('.pmt-account-org');
    if (org) { e.preventDefault(); if (org.getAttribute('aria-pressed') !== 'true') switchOrg(org); return; }
    var role = t.closest('.pmt-account-role');
    if (role && role.getAttribute('aria-pressed') !== 'true') { e.preventDefault(); switchRole(role); }
  });
  // The demo login's role in this sandbox: saved for the session, then the page opens again with it.
  function switchRole(button) {
    button.disabled = true;
    fetch(ACCOUNT + 'api/demo-role', {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json', 'X-Core-Request': '1'},
      body: JSON.stringify({app: button.getAttribute('data-app'), role: button.getAttribute('data-role')})})
      .then(function (r) { if (!r.ok) throw new Error('refused'); location.reload(); })
      .catch(function () { button.disabled = false; });
  }
  // Another organisation: the session works in it from now on, and the page opens again with its data.
  function switchOrg(button) {
    button.disabled = true;
    fetch(ACCOUNT + 'api/org', {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json', 'X-Core-Request': '1'},
      body: JSON.stringify({org: button.getAttribute('data-org')})})
      .then(function (r) { if (!r.ok) throw new Error('refused'); location.reload(); })
      .catch(function () { button.disabled = false; });
  }
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var open = document.querySelector('.pmt-account-button[aria-expanded="true"]');
    if (open) { setMenu(open, false); open.focus(); }
  });

  // ---- Unified Search (Core ADR-043): one box in the bar searches every Core application the person can open here ----
  // Each application answers its own <address>api/search?q= with only what this person may see, and the quick actions
  // their access allows: {results: [{kind, title, subtitle, url, actions: [{label, url}]}], more, all}. Nothing is copied
  // into Core. Only applications on this page's own site are asked (the browser's same-origin rule, and the gate's sign-in).
  var SEARCH_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>';
  var finder = {targets: [], timer: null, asked: 0, controllers: [], open: false};
  function sameSite(url) { try { return new URL(url, location.href).origin === location.origin; } catch (e) { return false; } }
  function searchSetup(me) {
    var slot = document.querySelector('.pmt-bar .pmt-search');
    if (!slot || !me.apps || !window.fetch || !window.URL) return;
    finder.targets = me.apps.filter(function (a) { return a.search && sameSite(a.search); });
    if (!finder.targets.length) return;
    slot.innerHTML = '<button type="button" class="pmt-search-toggle" aria-label="Search everything" title="Search everything">' + SEARCH_ICON + '</button>'
      + '<div class="pmt-search-box">' + SEARCH_ICON + '<input type="search" class="pmt-search-input" placeholder="Search everything" autocomplete="off" spellcheck="false"'
      + ' role="combobox" aria-expanded="false" aria-controls="pmt-search-results" aria-autocomplete="list" aria-label="Search across your applications">'
      + '<kbd class="pmt-search-key" aria-hidden="true">/</kbd></div>'
      + '<div class="pmt-search-results" id="pmt-search-results" role="listbox" aria-label="Search results" hidden></div>';
    slot.hidden = false;
    var input = slot.querySelector('.pmt-search-input');
    input.addEventListener('input', function () { clearTimeout(finder.timer); finder.timer = setTimeout(function () { runSearch(input.value); }, 180); });
    input.addEventListener('focus', function () { if (input.value.trim().length >= 2) showResults(true); });
    input.addEventListener('keydown', searchKeys);
    slot.querySelector('.pmt-search-toggle').addEventListener('click', function () {
      document.body.classList.add('pmt-search-wide'); input.focus();
    });
    document.addEventListener('click', function (e) { if (!e.target.closest || !e.target.closest('.pmt-search')) closeSearch(false); });
    document.addEventListener('keydown', function (e) {
      var t = e.target, typing = t && (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName));
      if ((e.key === '/' && !typing) || ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K'))) { e.preventDefault(); document.body.classList.add('pmt-search-wide'); input.focus(); input.select(); }
    });
    measure();
  }
  function resultsBox() { return document.getElementById('pmt-search-results'); }
  function showResults(show) {
    var box = resultsBox(), input = document.querySelector('.pmt-search-input');
    if (!box) return;
    box.hidden = !show; finder.open = show;
    if (input) input.setAttribute('aria-expanded', String(show));
  }
  function closeSearch(blur) {
    showResults(false);
    document.body.classList.remove('pmt-search-wide');
    if (blur) { var i = document.querySelector('.pmt-search-input'); if (i) i.blur(); }
  }
  function mark(text, words) {
    var out = esc(text);
    words.forEach(function (w) {
      if (w.length < 2) return;
      out = out.replace(new RegExp('(' + esc(w).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig'), '<mark>$1</mark>');
    });
    return out;
  }
  function runSearch(raw) {
    var q = raw.trim(), box = resultsBox();
    finder.controllers.forEach(function (c) { try { c.abort(); } catch (e) {} });
    finder.controllers = [];
    if (q.length < 2) { showResults(false); return; }
    var mine = ++finder.asked, words = q.toLowerCase().split(/\s+/);
    // The application this page belongs to answers first; the others follow in the order Core home lists them.
    var here = location.href, mineFirst = finder.targets.slice().sort(function (a, b) { return (here.indexOf(b.url) === 0) - (here.indexOf(a.url) === 0); });
    var groups = mineFirst.map(function (a) { return {app: a, state: 'asking', results: [], more: false, all: ''}; });
    var draw = function () {
      if (mine !== finder.asked) return;
      var found = groups.filter(function (g) { return g.results.length; });
      var waiting = groups.some(function (g) { return g.state === 'asking'; });
      var html = found.map(function (g) {
        var base = g.app.url;
        return '<section class="pmt-search-group" aria-label="' + esc(g.app.name) + '"><h3 class="pmt-search-app"><span>' + esc(g.app.name) + '</span>'
          + (g.all ? '<a class="pmt-search-all" href="' + esc(new URL(g.all, base).href) + '">See all</a>' : '') + '</h3>'
          + g.results.map(function (r) {
            var href = new URL(r.url || '', base).href;
            return '<div class="pmt-search-row"><a class="pmt-search-hit" role="option" href="' + esc(href) + '"><span class="pmt-search-title">' + mark(r.title || '', words) + '</span>'
              + (r.kind ? '<span class="pmt-search-kind">' + esc(r.kind) + '</span>' : '')
              + (r.subtitle ? '<span class="pmt-search-sub">' + mark(r.subtitle, words) + '</span>' : '') + '</a>'
              + ((r.actions || []).length ? '<span class="pmt-search-actions">' + r.actions.slice(0, 3).map(function (x) {
                return '<a class="pmt-search-action" href="' + esc(new URL(x.url || '', base).href) + '">' + esc(x.label) + '</a>';
              }).join('') + '</span>' : '') + '</div>';
          }).join('') + '</section>';
      }).join('');
      box.innerHTML = html + (waiting ? '<p class="pmt-search-note">Searching ' + groups.filter(function (g) { return g.state === 'asking'; }).map(function (g) { return esc(g.app.name); }).join(', ') + '…</p>'
        : found.length ? '' : '<p class="pmt-search-note">Nothing matches “' + esc(q) + '” in ' + (groups.length === 1 ? esc(groups[0].app.name) : 'your ' + groups.length + ' applications') + '.</p>');
      showResults(true);
    };
    groups.forEach(function (g) {
      var ctrl = window.AbortController ? new AbortController() : null;
      if (ctrl) { finder.controllers.push(ctrl); setTimeout(function () { try { ctrl.abort(); } catch (e) {} }, 5000); }
      var url = new URL(g.app.search, location.href); url.searchParams.set('q', q);
      fetch(url.href, {credentials: 'same-origin', headers: {Accept: 'application/json'}, redirect: 'error', signal: ctrl ? ctrl.signal : undefined})
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { g.state = 'done'; if (d && d.results) { g.results = d.results.slice(0, 6); g.more = !!d.more; g.all = d.all || ''; } draw(); })
        .catch(function () { g.state = 'done'; draw(); });
    });
    draw();
  }
  function searchKeys(e) {
    var box = resultsBox();
    if (e.key === 'Escape') { e.preventDefault(); closeSearch(true); return; }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    var links = box ? Array.prototype.slice.call(box.querySelectorAll('a')) : [];
    if (!links.length) return;
    e.preventDefault();
    links[e.key === 'ArrowDown' ? 0 : links.length - 1].focus();
  }
  document.addEventListener('keydown', function (e) {
    var box = resultsBox();
    if (!box || box.hidden || !e.target.closest || !e.target.closest('.pmt-search-results')) return;
    var links = Array.prototype.slice.call(box.querySelectorAll('a')), i = links.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); var n = i + (e.key === 'ArrowDown' ? 1 : -1); if (n < 0) { document.querySelector('.pmt-search-input').focus(); } else if (links[n]) links[n].focus(); }
    if (e.key === 'Escape') { e.preventDefault(); closeSearch(false); document.querySelector('.pmt-search-input').focus(); }
  });

  // ---- the bar ----
  // A sticky bar's real height (it can wrap on a narrow screen), for whatever sticks below it.
  function measure() {
    var b = document.querySelector('.pmt-bar');
    if (b && document.body.classList.contains('pmt-bar-sticky')) document.body.style.setProperty('--mf-shell-offset', b.offsetHeight + 'px');
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function bar() {
    if ('noBar' in data || document.querySelector('.pmt-bar')) return;
    var home = data.home || SITE;
    var label = data.homeLabel || 'projectmangotech.com';
    var mark = data.mark || (base + 'pmt-mark.svg');
    var el = document.createElement('header');
    el.className = 'pmt-bar';
    el.setAttribute('role', 'banner');
    el.innerHTML = '<div class="pmt-bar-inner">'
      + '<a class="pmt-bar-brand" href="' + esc(home) + '" title="' + esc(label) + '"><img class="pmt-bar-mark" src="' + esc(mark) + '" alt="" width="22" height="20">'
      + '<span class="pmt-bar-name">Project<em>Mango</em>Tech</span></a>'
      + (data.app ? '<span class="pmt-bar-sep" aria-hidden="true"></span><span class="pmt-bar-app">' + esc(data.app) + '</span>' : '')
      + '<span class="pmt-bar-notice" hidden title="A sandbox: fictional data, reset every night"><span class="pmt-bar-notice-dot" aria-hidden="true"></span>Sandbox<span class="pmt-bar-notice-more"> · demonstration data</span></span>'
      + '<span class="pmt-bar-spacer"></span>'
      + (ACCOUNT && !('noSearch' in data) ? '<div class="pmt-search" role="search" hidden></div>' : '')
      + '<span class="pmt-bar-spacer"></span>'
      + '<a class="pmt-bar-help" hidden>Help</a>'
      + (data.homeLink === 'off' ? '' : '<a class="pmt-bar-home" href="' + esc(home) + '"><span aria-hidden="true">&larr;</span> ' + esc(label) + '</a>')
      + (ACCOUNT ? '<span class="pmt-switch" hidden></span><span class="pmt-bell" hidden></span><span class="pmt-account"></span>' : '')
      + '<button type="button" class="pmt-theme-toggle"></button>'
      + '</div>';
    document.body.insertBefore(el, document.body.firstChild);
    document.body.classList.add('pmt-has-bar');
    if (data.sticky === 'on') {
      document.body.classList.add('pmt-bar-sticky');
      measure();
      window.addEventListener('resize', measure);
    }
    paintToggles(current());
  }

  apply(initial(), false);
  window.pmtTheme = {get: current, set: function (t) { return apply(t); }, toggle: toggle};
  window.pmtAppearance = {apply: function (a) { applyAppearance(a); }};
  window.addEventListener('storage', function (e) { if (e.key === KEY && valid(e.newValue) && e.newValue !== current()) apply(e.newValue, false); });
  if (document.body) bar(); else document.addEventListener('DOMContentLoaded', bar);
  document.addEventListener('DOMContentLoaded', function () { paintToggles(current()); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', accountMenus); else accountMenus();
})();
