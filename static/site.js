/* ItsRaiden site script. Everything is built with textContent so nothing users type can run as code. */
(function () {
  'use strict';
  var YT = 'https://www.youtube.com/@itsraidenfr';
  var CFG = {}, ME = null;

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      var v = attrs[k];
      if (v == null) continue;
      if (k === 'text') e.textContent = v;
      else if (k === 'class') e.className = v;
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    (kids || []).forEach(function (c) {
      if (c != null) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return e;
  }
  function api(method, path, body) {
    var o = { method: method, credentials: 'same-origin', headers: {} };
    if (body instanceof FormData) o.body = body;
    else if (body !== undefined) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(body); }
    return fetch(path, o).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, status: r.status, data: d }; });
    }).catch(function () { return { ok: false, status: 0, data: { error: 'Could not reach the server.' } }; });
  }
  function errMsg(r) { return (r.data && r.data.error) || 'Something went wrong. Try again!'; }
  function safeUrl(u) { return /^https:\/\/[^\s"'<>]+$/.test(u || '') ? u : ''; }
  function ytId(s) { return /^[\w-]{11}$/.test(s || '') ? s : null; }
  function say(node, text, good) { if (!node) return; node.textContent = text; node.className = 'msg' + (good ? ' ok' : ''); }

  /* ---------- links that come from the server config (Discord, SlinkGrenade) ---------- */
  function applyConfig() {
    $$('[data-needs]').forEach(function (e) {
      var key = e.getAttribute('data-needs');
      if (!(key === 'email' ? CFG.email : safeUrl(CFG[key]))) e.style.display = 'none';
    });
    $$('[data-link]').forEach(function (e) {
      var key = e.getAttribute('data-link');
      if (key === 'email') {
        if (/^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(CFG.email || '')) e.href = 'mailto:' + CFG.email;
        return;
      }
      var u = safeUrl(CFG[key]);
      if (u) { e.href = u; e.target = '_blank'; e.rel = 'noopener'; }
    });
  }

  /* ---------- header login box ---------- */
  function logout() { api('POST', '/api/logout', {}).then(function () { location.href = '/'; }); }
  function renderLogin() {
    var box = $('#login'); if (!box) return;
    box.textContent = '';
    if (ME) {
      box.appendChild(el('div', null, ['Welcome back, ', el('b', { text: ME.name }), '!']));
      var links = el('div', { class: 'loginlinks' }, [el('a', { href: '/account', text: 'My Account' })]);
      if (ME.admin) { links.appendChild(document.createTextNode(' | ')); links.appendChild(el('a', { href: '/admin', text: 'Admin' })); }
      links.appendChild(document.createTextNode(' | '));
      links.appendChild(el('a', { href: '#', text: 'Log out', onclick: function (e) { e.preventDefault(); logout(); } }));
      box.appendChild(links);
      return;
    }
    var u = el('input', { name: 'username', autocomplete: 'username', maxlength: '20', required: '' });
    var p = el('input', { type: 'password', name: 'password', autocomplete: 'current-password', maxlength: '128', required: '' });
    var msg = el('span', { class: 'loginerr' });
    var f = el('form', null, ['Username: ', u, ' Password: ', p, ' ', el('button', { class: 'btn', type: 'submit', text: 'Login' }),
      el('br'), el('a', { href: '/signup', text: 'Sign up FREE!' }), ' ', msg]);
    f.addEventListener('submit', function (e) {
      e.preventDefault(); msg.textContent = '';
      api('POST', '/api/login', { username: u.value, password: p.value }).then(function (r) {
        if (r.ok) location.reload(); else { msg.textContent = errMsg(r); p.value = ''; }
      });
    });
    box.appendChild(f);
  }

  /* ---------- visitor counter ---------- */
  function counter() {
    var c = $('#counter'); if (!c) return;
    api('POST', '/api/hit', {}).then(function (r) {
      if (!r.ok) return;
      var s = String(r.data.visitors);
      while (s.length < 7) s = '0' + s;
      c.textContent = '';
      for (var i = 0; i < s.length; i++) c.appendChild(el('span', { text: s[i] }));
    });
  }

  /* ---------- videos (newest uploads, fetched by the server) ---------- */
  function videos() {
    var grids = $$('.autogrid'), pl = $('#ytplayer'), h3 = $('.vidinfo h3');
    api('GET', '/api/videos').then(function (r) {
      var list = ((r.ok && r.data.videos) || []).filter(function (v) { return ytId(v.id); });
      grids.forEach(function (g) {
        g.textContent = '';
        if (!list.length) {
          g.appendChild(el('p', { class: 'empty' }, ["Couldn't load videos right now. ", el('a', { href: YT + '/videos', target: '_blank', rel: 'noopener', text: 'See them on YouTube!' })]));
          return;
        }
        list.slice(0, +g.getAttribute('data-count') || 8).forEach(function (v) {
          var url = 'https://www.youtube.com/watch?v=' + v.id, when = new Date(v.published);
          var img = el('div', { class: 'img' });
          img.style.backgroundImage = 'url(https://i.ytimg.com/vi/' + v.id + '/mqdefault.jpg)';
          if (Date.now() - when < 7 * 864e5) img.appendChild(el('em', { text: 'NEW!' }));
          g.appendChild(el('div', { class: 'th' }, [
            el('a', { href: url, target: '_blank', rel: 'noopener' }, [img]),
            el('p', null, [el('a', { href: url, target: '_blank', rel: 'noopener', text: v.title })]),
            el('small', { text: isNaN(when) ? '' : 'added ' + when.toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric' }) })
          ]));
        });
      });
      if (!list.length) return;
      var top = list[0];
      if (h3) h3.textContent = top.title;
      if (pl) pl.src = 'https://www.youtube-nocookie.com/embed/' + top.id;
    });
  }

  /* ---------- shoutbox ---------- */
  function shoutbox() {
    var list = $('#shout'), formBox = $('#shoutform'); if (!list) return;
    var jump = true;
    function load() {
      api('GET', '/api/shouts').then(function (r) {
        if (!r.ok) return;
        var atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 5;
        list.textContent = '';
        if (!r.data.shouts.length) list.appendChild(el('div', { class: 'empty', text: 'No shouts yet. Be the first!' }));
        r.data.shouts.forEach(function (s) {
          var d = el('div', { title: new Date(s.at * 1000).toLocaleString() }, [el('b', { text: s.user + ': ' }), s.body]);
          if (s.can_delete) d.appendChild(el('a', { href: '#', class: 'x', title: 'Delete', text: '×', onclick: function (e) {
            e.preventDefault();
            if (confirm('Delete this shout?')) api('DELETE', '/api/shouts/' + s.id).then(load);
          } }));
          list.appendChild(d);
        });
        if (atBottom || jump) list.scrollTop = list.scrollHeight;
        jump = false;
      });
    }
    formBox.textContent = '';
    if (ME) {
      var m = el('input', { class: 'txt', maxlength: '200', placeholder: 'say something!' }), msg = el('div', { class: 'msg' });
      var f = el('form', null, [m, el('br'), el('button', { class: 'btn', type: 'submit', text: 'Shout!', style: 'margin-top:3px' }), msg]);
      f.addEventListener('submit', function (e) {
        e.preventDefault(); msg.textContent = '';
        if (!m.value.trim()) return;
        api('POST', '/api/shouts', { body: m.value }).then(function (r) {
          if (r.ok) { m.value = ''; jump = true; load(); } else msg.textContent = errMsg(r);
        });
      });
      formBox.appendChild(f);
    } else {
      formBox.appendChild(el('div', { class: 'needlogin' }, [el('a', { href: '/signup', text: 'Sign up' }), ' or log in to shout!']));
    }
    load();
    setInterval(load, 30000);
  }

  /* ---------- poll ---------- */
  function poll() {
    var box = $('#poll'); if (!box) return;
    function render(p) {
      box.textContent = '';
      if (!p) { box.appendChild(el('i', { text: 'No poll right now!' })); return; }
      box.appendChild(el('b', { text: p.question }));
      var total = p.options.reduce(function (a, o) { return a + o.votes; }, 0);
      if (p.my_vote || !ME) {
        var res = el('div', { class: 'pollres' });
        p.options.forEach(function (o) {
          var pc = total ? Math.round(o.votes / total * 100) : 0, bar = el('i');
          bar.style.width = pc + '%';
          res.appendChild(el('div', null, [(o.id === p.my_vote ? '✔ ' : '') + o.label + ' (' + pc + '%)', bar]));
        });
        box.appendChild(res);
        var note = total + ' vote' + (total === 1 ? '' : 's');
        box.appendChild(el('small', null, ME ? [note] : [note + ' — ', el('a', { href: '/signup', text: 'sign up' }), ' or log in to vote!']));
        return;
      }
      var f = el('form'), msg = el('div', { class: 'msg' });
      p.options.forEach(function (o) {
        f.appendChild(el('label', null, [el('input', { type: 'radio', name: 'p', value: String(o.id) }), ' ' + o.label]));
      });
      f.appendChild(el('button', { class: 'btn g', type: 'submit', text: 'VOTE!' }));
      f.appendChild(msg);
      f.addEventListener('submit', function (e) {
        e.preventDefault();
        var c = $('input:checked', f);
        if (!c) { msg.textContent = 'Pick one first!'; return; }
        api('POST', '/api/poll/vote', { option_id: +c.value }).then(function (r) { if (r.ok) render(r.data.poll); else msg.textContent = errMsg(r); });
      });
      box.appendChild(f);
    }
    api('GET', '/api/poll').then(function (r) { if (r.ok) render(r.data.poll); else box.textContent = ''; });
  }

  /* ---------- pics ---------- */
  function showPic(url, cap) {
    var lb = $('#lightbox');
    $('img', lb).src = url; $('span', lb).textContent = cap;
    lb.style.display = 'flex';
  }
  function pics() {
    var g = $('#pics'); if (!g) return;
    api('GET', '/api/pics').then(function (r) {
      g.textContent = '';
      var list = (r.ok && r.data.pics) || [];
      if (!list.length) { g.appendChild(el('p', { class: 'empty', text: 'No pics yet... check back soon!' })); return; }
      list.forEach(function (p) {
        if (!/^\/pics\/[a-f0-9]{32}\.webp$/.test(p.url)) return;
        var ph = el('div', { class: 'ph' });
        ph.style.backgroundImage = 'url(' + p.url + ')';
        g.appendChild(el('div', { class: 'pol', onclick: function () { showPic(p.url, p.caption); } }, [ph, el('p', { text: p.caption || ' ' })]));
      });
    });
  }

  /* ---------- sign up page ---------- */
  function signupPage() {
    var f = $('#signupform'); if (!f) return;
    if (ME) { f.style.display = 'none'; $('#signedin').style.display = ''; return; }
    // Optional Cloudflare Turnstile robot check (only if the site owner turned it on)
    var tsId = null;
    if (/^[\w-]+$/.test(CFG.turnstile || '') && $('#turnstile')) {
      window.__tsReady = function () { tsId = window.turnstile.render('#turnstile', { sitekey: CFG.turnstile }); };
      var sc = document.createElement('script');
      sc.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?onload=__tsReady&render=explicit';
      sc.async = true;
      document.head.appendChild(sc);
    }
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var msg = $('#signupmsg');
      if (f.password.value !== f.password2.value) { say(msg, "Those passwords don't match!"); return; }
      say(msg, 'Creating your account...', true);
      var ts = (tsId !== null && window.turnstile) ? window.turnstile.getResponse(tsId) || '' : '';
      api('POST', '/api/signup', { username: f.username.value, password: f.password.value, turnstile: ts }).then(function (r) {
        if (r.ok) { location.href = '/'; return; }
        say(msg, errMsg(r));
        if (tsId !== null && window.turnstile) window.turnstile.reset(tsId);
      });
    });
  }

  /* ---------- my account page ---------- */
  function accountPage() {
    if (!$('#acct-in')) return;
    if (!ME) { $('#acct-out').style.display = ''; return; }
    $('#acct-in').style.display = '';
    $('#acct-name').textContent = ME.name;
    $('#logoutbtn').addEventListener('click', logout);
    var pf = $('#pwform');
    pf.addEventListener('submit', function (e) {
      e.preventDefault();
      var msg = $('#pwmsg');
      if (pf.new.value !== pf.new2.value) { say(msg, "Those new passwords don't match!"); return; }
      api('POST', '/api/account/password', { current: pf.current.value, new: pf.new.value }).then(function (r) {
        if (r.ok) { pf.reset(); say(msg, 'Password changed! You were logged out on your other devices.', true); }
        else say(msg, errMsg(r));
      });
    });
    var df = $('#delform');
    df.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!confirm('Really delete your account forever?')) return;
      api('POST', '/api/account/delete', { password: df.password.value }).then(function (r) {
        if (r.ok) location.href = '/'; else say($('#delmsg'), errMsg(r));
      });
    });
  }

  /* ---------- admin page ---------- */
  function adminPage() {
    if (!$('#admin-yes')) return;
    if (!ME || !ME.admin) { $('#admin-no').style.display = ''; return; }
    $('#admin-yes').style.display = '';

    function loadPics() {
      api('GET', '/api/pics').then(function (r) {
        var box = $('#adminpics'); box.textContent = '';
        ((r.ok && r.data.pics) || []).forEach(function (p) {
          var ph = el('div', { class: 'ph' }); ph.style.backgroundImage = 'url(' + p.url + ')';
          box.appendChild(el('div', null, [ph, p.caption, el('br'), el('a', { href: '#', text: 'delete', onclick: function (e) {
            e.preventDefault();
            if (confirm('Delete this pic?')) api('DELETE', '/api/admin/pics/' + p.id).then(loadPics);
          } })]));
        });
      });
    }
    var picf = $('#picform');
    picf.addEventListener('submit', function (e) {
      e.preventDefault();
      say($('#picmsg'), 'Uploading...', true);
      api('POST', '/api/admin/pics', new FormData(picf)).then(function (r) {
        if (r.ok) { picf.reset(); say($('#picmsg'), 'Uploaded!', true); loadPics(); } else say($('#picmsg'), errMsg(r));
      });
    });
    loadPics();

    var pollf = $('#pollform');
    pollf.addEventListener('submit', function (e) {
      e.preventDefault();
      var opts = $$('input[name=opt]', pollf).map(function (i) { return i.value; }).filter(function (v) { return v.trim(); });
      api('POST', '/api/admin/poll', { question: pollf.question.value, options: opts }).then(function (r) {
        if (r.ok) { pollf.reset(); say($('#pollmsg'), 'New poll is live!', true); poll(); } else say($('#pollmsg'), errMsg(r));
      });
    });

    function loadUsers() {
      api('GET', '/api/admin/users').then(function (r) {
        var t = $('#users'); t.textContent = '';
        t.appendChild(el('tr', null, [el('th', { text: 'Username' }), el('th', { text: 'Joined' }), el('th', { text: 'Status' }), el('th')]));
        ((r.ok && r.data.users) || []).forEach(function (u) {
          var action = u.is_admin ? el('i', { text: 'admin' }) : el('button', { class: 'btn' + (u.banned ? ' g' : ' danger'), type: 'button', text: u.banned ? 'Unban' : 'Ban', onclick: function () {
            if (!u.banned && !confirm('Ban ' + u.username + '? Their shouts get hidden and they get logged out.')) return;
            api('POST', '/api/admin/users/' + u.id + '/ban', { banned: !u.banned }).then(loadUsers);
          } });
          t.appendChild(el('tr', null, [el('td', { text: u.username }), el('td', { text: new Date(u.created_at * 1000).toLocaleDateString('en-CA') }),
            el('td', { text: u.banned ? 'BANNED' : 'ok' }), el('td', null, [action])]));
        });
      });
    }
    loadUsers();
  }

  /* ---------- start ---------- */
  var lb = $('#lightbox');
  if (lb) lb.addEventListener('click', function () { lb.style.display = 'none'; });

  Promise.all([api('GET', '/api/config'), api('GET', '/api/me')]).then(function (rs) {
    CFG = (rs[0].ok && rs[0].data) || {};
    ME = (rs[1].ok && rs[1].data.user) || null;
    applyConfig(); renderLogin(); counter(); videos(); shoutbox(); poll(); pics();
    signupPage(); accountPage(); adminPage();
  });
})();
