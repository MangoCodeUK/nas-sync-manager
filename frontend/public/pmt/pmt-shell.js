// ProjectMangoTech brand shell: one theme preference shared by the site and every app on *.projectmangotech.com,
// and a slim bar at the top of each app with the way back to the main site and the light/dark switch.
//
//   <script src="pmt/pmt-shell.js" data-app="NAS Sync Manager"></script>
//
// Attributes on the script tag: data-app (the app's name in the bar), data-home (the link back, default
// https://projectmangotech.com/), data-home-label, data-default ("dark" or "light" when nothing is stored and the
// browser has no preference), data-no-bar (apply the theme only; the page draws its own bar), data-mark (path to the
// logo mark, default pmt-mark.svg next to this script).
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
  var domain = /(^|\.)projectmangotech\.com$/.test(host) ? '.projectmangotech.com' : '';
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
  function toggle() { return apply(current() === 'dark' ? 'light' : 'dark'); }
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('.pmt-theme-toggle') : null;
    if (b) { e.preventDefault(); toggle(); }
  });

  // ---- the bar ----
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function bar() {
    if ('noBar' in data || document.querySelector('.pmt-bar')) return;
    var home = data.home || 'https://projectmangotech.com/';
    var label = data.homeLabel || 'projectmangotech.com';
    var mark = data.mark || (base + 'pmt-mark.svg');
    var el = document.createElement('header');
    el.className = 'pmt-bar';
    el.setAttribute('role', 'banner');
    el.innerHTML = '<div class="pmt-bar-inner">'
      + '<a class="pmt-bar-brand" href="' + esc(home) + '"><img class="pmt-bar-mark" src="' + esc(mark) + '" alt="" width="22" height="20">'
      + '<span class="pmt-bar-name">Project<em>Mango</em>Tech</span></a>'
      + (data.app ? '<span class="pmt-bar-sep" aria-hidden="true"></span><span class="pmt-bar-app">' + esc(data.app) + '</span>' : '')
      + '<span class="pmt-bar-spacer"></span>'
      + '<a class="pmt-bar-home" href="' + esc(home) + '"><span aria-hidden="true">&larr;</span> ' + esc(label) + '</a>'
      + '<button type="button" class="pmt-theme-toggle"></button>'
      + '</div>';
    document.body.insertBefore(el, document.body.firstChild);
    document.body.classList.add('pmt-has-bar');
    paintToggles(current());
  }

  apply(initial(), false);
  window.pmtTheme = {get: current, set: function (t) { return apply(t); }, toggle: toggle};
  window.addEventListener('storage', function (e) { if (e.key === KEY && valid(e.newValue) && e.newValue !== current()) apply(e.newValue, false); });
  if (document.body) bar(); else document.addEventListener('DOMContentLoaded', bar);
  document.addEventListener('DOMContentLoaded', function () { paintToggles(current()); });
})();
