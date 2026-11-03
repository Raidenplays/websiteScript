/* Raiden Site Manager - window logic. All text is inserted with textContent (never as HTML). */
(function () {
  'use strict';
  var site = window.site;
  var S = { server: '', name: '', content: null, saved: null, version: 0, dirty: false, view: 'pages', tab: 0 };

  /* ------------------------------------------------------------ helpers */
  function $(s, r) { return (r || document).querySelector(s); }
  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      var v = attrs[k];
      if (v == null || v === false) continue;
      if (k === 'text') e.textContent = v;
      else if (k === 'class') e.className = v;
      else if (k === 'value') e.value = v;
      else if (k === 'checked') e.checked = !!v;
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : v);
    }
    (kids || []).forEach(function (c) { if (c != null && c !== false) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function err(r) { return (r && r.data && r.data.error) || 'Something went wrong.'; }
  var toastTimer;
  function toast(text, bad) {
    var t = $('#toast'); t.textContent = text; t.className = bad ? 'err' : '';
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.className = 'hidden'; }, 3200);
  }
  function api(m, p, b) { return site.api(m, p, b).then(function (r) { if (r.status === 401) { toast('Your login expired. Please log in again.', true); showLogin(); } return r; }); }
  function field(label, input, hint) { return el('label', null, [label, hint ? el('span', { class: 'hint', text: ' ' + hint }) : null, input]); }
  function input(obj, key, attrs, onchange) {
    var i = el('input', Object.assign({ value: obj[key] == null ? '' : obj[key] }, attrs || {}));
    i.addEventListener('input', function () { obj[key] = i.value; if (onchange) onchange(); });
    return i;
  }
  function textarea(obj, key, rows, onchange) {
    var t = el('textarea', { rows: rows || 5 }); t.value = obj[key] || '';
    t.addEventListener('input', function () { obj[key] = t.value; if (onchange) onchange(); });
    return t;
  }
  function select(obj, key, options, onchange) {
    var s = el('select');
    options.forEach(function (o) { var v = Array.isArray(o) ? o[0] : o, l = Array.isArray(o) ? o[1] : o; s.appendChild(el('option', { value: v, text: l })); });
    s.value = obj[key] == null ? (Array.isArray(options[0]) ? options[0][0] : options[0]) : obj[key];
    s.addEventListener('change', function () { obj[key] = s.value; if (onchange) onchange(); });
    return s;
  }
  function move(arr, i, d) { var j = i + d; if (j < 0 || j >= arr.length) return; var t = arr[i]; arr[i] = arr[j]; arr[j] = t; }
  function fmtTime(sec) { return new Date(sec * 1000).toLocaleString('en-CA', { dateStyle: 'medium', timeStyle: 'short' }); }
  var FORMAT_HELP = function () {
    return el('div', { class: 'help' }, ['Formatting: ', el('code', { text: '**bold**' }), ' ', el('code', { text: '*italic*' }), ' ',
      el('code', { text: '[link text](https://...)' }), ' • start a line with ', el('code', { text: '- ' }), ' for a bullet • leave a blank line for a new paragraph']);
  };

  /* ------------------------------------------------------------ modal */
  function modal(title, body, buttons) {
    $('#mtitle').textContent = title;
    var b = $('#mbody'); b.textContent = ''; b.appendChild(body);
    var f = $('#mfoot'); f.textContent = '';
    var msg = el('div', { class: 'msg' }); f.appendChild(msg);
    buttons.forEach(function (bt) { f.appendChild(el('button', { class: bt.cls || '', text: bt.label, onclick: function () { bt.click(msg); } })); });
    $('#modal').className = '';
    var first = b.querySelector('input,textarea,select'); if (first) first.focus();
  }
  function closeModal() { $('#modal').className = 'hidden'; }
  $('#mclose').addEventListener('click', closeModal);

  /* ------------------------------------------------------------ dirty state */
  function markDirty() {
    S.dirty = JSON.stringify(S.content) !== JSON.stringify(S.saved);
    $('#savebar').className = S.dirty ? '' : 'hidden';
    site.setDirty(S.dirty);
  }
  function save() {
    var btn = $('#savebtn'); btn.disabled = true;
    api('PUT', '/api/admin/content', { version: S.version, content: S.content }).then(function (r) {
      btn.disabled = false;
      if (!r.ok) { toast(err(r), true); return; }
      S.version = r.data.version; S.content = r.data.content; S.saved = clone(r.data.content);
      markDirty(); toast('Saved! Your site is updated.'); render();
    });
  }
  $('#savebtn').addEventListener('click', save);
  $('#discardbtn').addEventListener('click', function () {
    if (!confirm('Throw away all unsaved changes?')) return;
    S.content = clone(S.saved); markDirty(); render();
  });

  /* ------------------------------------------------------------ login */
  function showLogin(server, username) {
    $('#appview').className = 'hidden'; $('#loginview').className = '';
    var f = $('#loginform');
    if (server) f.server.value = server.replace(/^https:\/\//, '');
    if (username) f.username.value = username;
    (f.username.value ? f.password : f.server).focus();
  }
  $('#loginform').addEventListener('submit', function (e) {
    e.preventDefault();
    var f = e.target, msg = $('#loginmsg');
    msg.className = 'msg ok'; msg.textContent = 'Logging in...';
    site.login({ server: f.server.value, username: f.username.value, password: f.password.value, remember: f.remember.checked }).then(function (r) {
      f.password.value = '';
      if (!r.ok) { msg.className = 'msg'; msg.textContent = err(r); return; }
      msg.textContent = '';
      start(r.data.server, r.data.name);
    });
  });
  $('#logoutbtn').addEventListener('click', function () {
    if (S.dirty && !confirm('You have unsaved changes. Log out anyway?')) return;
    site.logout().then(function () { S.dirty = false; site.setDirty(false); showLogin(S.server); });
  });
  $('#viewsite').addEventListener('click', function () {
    var t = S.content && S.content.tabs[S.tab];
    site.open(S.view === 'pages' && t && S.tab > 0 ? '/' + t.slug : '/');
  });

  function start(server, name) {
    S.server = server; S.name = name;
    $('#who').textContent = 'Logged in as ' + name;
    $('#loginview').className = 'hidden'; $('#appview').className = '';
    api('GET', '/api/admin/content').then(function (r) {
      if (!r.ok) { toast(err(r), true); return; }
      S.version = r.data.version; S.content = r.data.content; S.saved = clone(r.data.content); S.tab = 0;
      markDirty(); go('pages');
    });
  }

  /* ------------------------------------------------------------ navigation */
  Array.prototype.forEach.call(document.querySelectorAll('#sidenav a'), function (a) {
    a.addEventListener('click', function () { go(a.getAttribute('data-view')); });
  });
  function go(v) {
    S.view = v;
    Array.prototype.forEach.call(document.querySelectorAll('#sidenav a'), function (a) { a.className = a.getAttribute('data-view') === v ? 'on' : ''; });
    render();
  }
  function render() {
    var view = $('#view'); view.textContent = '';
    ({ pages: viewPages, settings: viewSettings, blog: viewBlog, pics: viewPics, poll: viewPoll, shouts: viewShouts, users: viewUsers, history: viewHistory })[S.view](view);
  }
  function panel(title, cls, body, headExtra) {
    return el('div', { class: 'panel' }, [el('div', { class: 'ph ' + (cls || '') }, [el('span', { text: title }), el('span', { class: 'spacer' })].concat(headExtra || [])), el('div', { class: 'pb' }, body)]);
  }

  /* ------------------------------------------------------------ pages & sections */
  var TYPES = {
    text: 'Text / About me', items: 'List of entries (projects, education, skills...)', links: 'Links & buttons',
    blog: 'Blog posts', player: 'YouTube player (latest video)', videos: 'Video grid (latest uploads)', pics: 'Photo album',
    marquee: 'Scrolling text', discord: 'Discord join button', poll: 'Poll', shoutbox: 'Shoutbox', counter: 'Visitor counter',
  };
  var NEW_SECTION = {
    text: { title: 'NEW SECTION', text: 'Write something here!', badge: '', buttons: [] },
    items: { title: 'NEW LIST', items: [] },
    links: { title: 'LINKS', style: 'list', items: [] },
    blog: { title: 'LATEST POSTS', count: 20 }, player: { title: '★ LATEST UPLOAD' }, videos: { title: 'LATEST VIDEOS', count: 8 },
    pics: { title: 'PHOTO ALBUM' }, marquee: { text: '*** WELCOME!!! ***' }, discord: { title: 'JOIN THE DISCORD', text: 'Come hang out!' },
    poll: { title: 'POLL!!!' }, shoutbox: { title: 'SHOUTBOX' }, counter: { title: 'You are visitor number:' },
  };
  var COLOR_CLASS = { green: '', orange: 'or', black: 'bk' };
  var LINK_OPTIONS = [['@email', 'Your email (from settings)'], ['@linkedin', 'Your LinkedIn'], ['@github', 'Your GitHub'], ['@youtube', 'Your YouTube channel'],
    ['@coffee', 'Buy Me a Coffee'], ['@discord', 'Discord invite'], ['@slinkgrenade', "SlinkGrenade's channel"]];

  function linkInput(obj, key, onchange) {
    var listId = 'links-' + Math.random().toString(36).slice(2);
    var dl = el('datalist', { id: listId });
    LINK_OPTIONS.forEach(function (o) { dl.appendChild(el('option', { value: o[0], text: o[1] })); });
    S.content.tabs.forEach(function (t, i) { dl.appendChild(el('option', { value: i === 0 ? '/' : '/' + t.slug, text: 'Page: ' + t.title })); });
    var i = input(obj, key, { list: listId, placeholder: 'https://...  or  /blog  or  @email' }, onchange);
    var wrap = el('span', null, [i, dl]);
    return wrap;
  }

  function viewPages(view) {
    var c = S.content, tabs = c.tabs;
    if (S.tab >= tabs.length) S.tab = 0;
    view.appendChild(el('h2', { text: 'Pages & Sections' }));
    view.appendChild(el('p', { class: 'sub', text: 'Each tab at the top of your site is a page. Pick one to edit its sections. Changes go live when you click Save & publish.' }));

    // tab list
    var list = el('div', { class: 'tablist' });
    tabs.forEach(function (t, i) {
      list.appendChild(el('div', { class: 'item' + (i === S.tab ? ' sel' : ''), onclick: function () { S.tab = i; render(); } }, [
        el('span', { class: 'name' }, [t.title, i === 0 ? el('span', { class: 'tag home', text: 'home' }) : null, t.hidden ? el('span', { class: 'tag', text: 'hidden' }) : null]),
        el('button', { class: 'icon', title: 'Move left', text: '▲', disabled: i <= 1, onclick: function (e) { e.stopPropagation(); move(tabs, i, -1); S.tab = i - 1; markDirty(); render(); } }),
        el('button', { class: 'icon', title: 'Move right', text: '▼', disabled: i === 0 || i === tabs.length - 1, onclick: function (e) { e.stopPropagation(); move(tabs, i, 1); S.tab = i + 1; markDirty(); render(); } }),
      ]));
    });
    var addTab = el('button', { text: '+ Add tab', onclick: function () {
      var n = tabs.length + 1, slug = 'page-' + n;
      while (tabs.some(function (t) { return t.slug === slug; })) slug = 'page-' + (++n);
      tabs.push({ slug: slug, title: 'New Tab', hidden: false, heading: 'NEW PAGE', subheading: '', page_title: '',
        main: [Object.assign({ type: 'text', color: 'green' }, clone(NEW_SECTION.text))], side: [{ type: 'counter', title: 'You are visitor number:', color: 'green' }] });
      S.tab = tabs.length - 1; markDirty(); render();
    } });
    var left = panel('Tabs', '', [list, el('div', { class: 'addrow' }, [addTab])]);

    // selected tab
    var t = tabs[S.tab], isHome = S.tab === 0;
    var settingsBody = [
      el('div', { class: 'row' }, [
        field('Tab name', input(t, 'title', { maxlength: 20 }, function () { markDirty(); var n = list.children[S.tab].querySelector('.name'); n.firstChild.textContent = t.title; })),
        isHome ? field('Web address', el('input', { value: '/ (home page)', disabled: true }))
          : field('Web address', input(t, 'slug', { maxlength: 30 }, markDirty), '(lowercase, numbers, dashes)'),
      ]),
      el('div', { class: 'row' }, [field('Page heading', input(t, 'heading', { maxlength: 60 }, markDirty), '(big text at the top, optional)'),
        field('Browser tab title', input(t, 'page_title', { maxlength: 80 }, markDirty), '(optional)')]),
      field('Intro line under the heading', input(t, 'subheading', { maxlength: 300 }, markDirty), '(optional, formatting works)'),
      isHome ? null : el('label', { class: 'check' }, [el('input', { type: 'checkbox', checked: t.hidden, onchange: function (e) { t.hidden = e.target.checked; markDirty(); render(); } }), 'Hide from the menu (the page still works if someone has the link)']),
    ];
    var del = isHome ? [] : [el('button', { class: 'danger', text: 'Delete tab', onclick: function () {
      if (!confirm('Delete the "' + t.title + '" tab and everything on it?')) return;
      tabs.splice(S.tab, 1); S.tab = Math.max(0, S.tab - 1); markDirty(); render();
    } })];
    var right = el('div', null, [
      panel('Tab: ' + t.title, 'or', settingsBody, del),
      el('div', { class: 'cols' }, [sectionPanel(t, 'main', 'Main column'), sectionPanel(t, 'side', 'Sidebar')]),
    ]);
    view.appendChild(el('div', { class: 'pages' }, [left, right]));
  }

  function sectionPanel(tab, col, label) {
    var secs = tab[col], box = el('div', { class: 'seclist' });
    if (!secs.length) box.appendChild(el('div', { class: 'empty', text: 'No sections yet.' }));
    secs.forEach(function (s, i) {
      box.appendChild(el('div', { class: 'sec ' + (COLOR_CLASS[s.color] || '') }, [
        el('div', { class: 'info' }, [el('b', { text: s.title || (s.type === 'marquee' ? s.text : '(no title)') }), el('small', { text: TYPES[s.type] })]),
        el('button', { class: 'icon', text: '▲', title: 'Move up', disabled: i === 0, onclick: function () { move(secs, i, -1); markDirty(); render(); } }),
        el('button', { class: 'icon', text: '▼', title: 'Move down', disabled: i === secs.length - 1, onclick: function () { move(secs, i, 1); markDirty(); render(); } }),
        el('button', { text: 'Edit', onclick: function () { editSection(secs, i); } }),
        el('button', { class: 'icon danger', text: '✕', title: 'Delete', onclick: function () {
          if (!confirm('Delete the "' + (s.title || TYPES[s.type]) + '" section?')) return;
          secs.splice(i, 1); markDirty(); render();
        } }),
      ]));
    });
    var used = tab.main.concat(tab.side).map(function (s) { return s.type; });
    var single = ['player', 'videos', 'pics', 'poll', 'shoutbox', 'counter', 'blog'];
    var sel = el('select');
    sel.appendChild(el('option', { value: '', text: 'Add a section...' }));
    Object.keys(TYPES).forEach(function (k) {
      if (single.indexOf(k) >= 0 && used.indexOf(k) >= 0) return;
      sel.appendChild(el('option', { value: k, text: TYPES[k] }));
    });
    sel.addEventListener('change', function () {
      if (!sel.value) return;
      secs.push(Object.assign({ type: sel.value, color: 'green', link_label: '', link_url: '' }, clone(NEW_SECTION[sel.value])));
      markDirty(); render(); editSection(secs, secs.length - 1);
    });
    return panel(label, 'bk', [box, el('div', { class: 'addrow' }, [sel])]);
  }

  function editSection(secs, i) {
    var s = clone(secs[i]), body = el('div');
    var t = s.type;
    body.appendChild(el('p', { class: 'hint', text: TYPES[t] }));
    if (t !== 'marquee') {
      body.appendChild(el('div', { class: 'row' }, [
        field(t === 'counter' ? 'Label' : 'Box title', input(s, 'title', { maxlength: 60 })),
        t === 'counter' ? null : el('div', { class: 'narrow' }, [field('Header colour', select(s, 'color', [['green', 'Green'], ['orange', 'Orange'], ['black', 'Black']]))]),
      ]));
    }
    if (['text', 'items', 'links', 'player', 'videos', 'blog', 'pics'].indexOf(t) >= 0) {
      body.appendChild(el('div', { class: 'row' }, [field('Header link text', input(s, 'link_label', { maxlength: 30, placeholder: 'e.g. view all' }), '(optional)'),
        field('Header link goes to', linkInput(s, 'link_url'))]));
    }
    if (t === 'text') {
      body.appendChild(field('Text', textarea(s, 'text', 9)));
      body.appendChild(FORMAT_HELP());
      body.appendChild(field('Picture badge', input(s, 'badge', { maxlength: 3, placeholder: 'e.g. RB' }), '(up to 3 letters shown in a square next to the text; leave empty for none)'));
      body.appendChild(el('label', { text: 'Buttons' }));
      body.appendChild(linkListEditor(s.buttons = s.buttons || [], 4, false));
    } else if (t === 'items') {
      body.appendChild(el('label', { text: 'Entries' }));
      body.appendChild(itemsEditor(s.items = s.items || []));
    } else if (t === 'links') {
      body.appendChild(field('Style', select(s, 'style', [['list', 'Simple list'], ['buttons', 'Buttons'], ['boxes', 'Big boxes with a description'], ['badges', 'Retro 88x31 badges']], function () { redraw(); })));
      var holder = el('div'); body.appendChild(el('label', { text: 'Links' })); body.appendChild(holder);
      var redraw = function () { holder.textContent = ''; holder.appendChild(linkListEditor(s.items = s.items || [], 20, s.style)); };
      redraw();
    } else if (t === 'videos' || t === 'blog') {
      body.appendChild(field(t === 'videos' ? 'How many videos' : 'How many posts', input(s, 'count', { type: 'number', min: 1, max: t === 'videos' ? 15 : 50 })));
      if (t === 'blog') body.appendChild(el('p', { class: 'hint', text: 'Write posts in the Blog section of this app.' }));
    } else if (t === 'marquee' || t === 'discord') {
      body.appendChild(field(t === 'marquee' ? 'Scrolling text' : 'Text above the button', input(s, 'text', { maxlength: 400 })));
      if (t === 'discord') body.appendChild(el('p', { class: 'hint', text: "The button uses DISCORD_INVITE from the server's .env file. If that's empty, this box is hidden." }));
    } else if (t === 'poll') {
      body.appendChild(el('p', { class: 'hint', text: 'Change the question and answers in the Poll section of this app.' }));
    } else if (t === 'pics') {
      body.appendChild(el('p', { class: 'hint', text: 'Upload pictures in the Pics section of this app.' }));
    }
    modal('Edit section', body, [
      { label: 'Cancel', click: closeModal },
      { label: 'Done', cls: 'primary', click: function () { if (s.count != null) s.count = parseInt(s.count, 10) || 1; secs[i] = s; markDirty(); closeModal(); render(); } },
    ]);
  }

  function itemsEditor(items) {
    var wrap = el('div');
    function draw(openIndex) {
      wrap.textContent = '';
      items.forEach(function (it, i) {
        var bodyEl = el('div', { class: 'eb' + (i === openIndex ? '' : ' hidden') });
        var head = el('div', { class: 'eh', onclick: function () { bodyEl.classList.toggle('hidden'); } }, [
          el('b', { text: (it.icon ? '[' + it.icon + '] ' : '') + (it.title || '(untitled)') }),
          el('button', { class: 'icon', text: '▲', disabled: i === 0, onclick: function (e) { e.stopPropagation(); move(items, i, -1); draw(i - 1); } }),
          el('button', { class: 'icon', text: '▼', disabled: i === items.length - 1, onclick: function (e) { e.stopPropagation(); move(items, i, 1); draw(i + 1); } }),
          el('button', { class: 'icon danger', text: '✕', onclick: function (e) { e.stopPropagation(); if (confirm('Remove "' + (it.title || 'this entry') + '"?')) { items.splice(i, 1); draw(-1); } } }),
        ]);
        it.tagsText = (it.tags || []).join(', ');
        var tagsInput = input(it, 'tagsText', { placeholder: 'Debian, Docker, Linux' }, function () { it.tags = it.tagsText.split(',').map(function (x) { return x.trim(); }).filter(Boolean); });
        bodyEl.appendChild(el('div', { class: 'row' }, [
          field('Title', input(it, 'title', { maxlength: 100 }, function () { head.querySelector('b').textContent = (it.icon ? '[' + it.icon + '] ' : '') + (it.title || '(untitled)'); })),
          field('Small line under title', input(it, 'subtitle', { maxlength: 100 }), '(optional)'),
        ]));
        bodyEl.appendChild(el('div', { class: 'row' }, [
          el('div', { class: 'narrow' }, [field('Icon', input(it, 'icon', { maxlength: 3, placeholder: 'IT' }))]),
          el('div', { class: 'narrow' }, [field('Icon colour', select(it, 'icon_color', ['green', 'lime', 'blue', 'orange', 'purple', 'red', 'gray', 'brown']))]),
          field('Tags', tagsInput, '(comma separated, optional)'),
        ]));
        bodyEl.appendChild(field('Title links to', linkInput(it, 'url'), '(optional)'));
        bodyEl.appendChild(field('Description', textarea(it, 'text', 5)));
        bodyEl.appendChild(FORMAT_HELP());
        wrap.appendChild(el('div', { class: 'entry' }, [head, bodyEl]));
      });
      if (!items.length) wrap.appendChild(el('div', { class: 'empty', text: 'No entries yet.' }));
      wrap.appendChild(el('button', { text: '+ Add entry', disabled: items.length >= 30, onclick: function () {
        items.push({ icon: '', icon_color: 'green', title: 'New entry', subtitle: '', tags: [], text: '', url: '' }); draw(items.length - 1);
      } }));
    }
    draw(-1);
    return wrap;
  }

  function linkListEditor(items, max, style) {
    var wrap = el('div');
    function draw() {
      wrap.textContent = '';
      items.forEach(function (l, i) {
        var row = el('div', { class: 'row', style: 'margin-bottom:6px' }, [
          el('div', null, [input(l, 'label', { maxlength: 40, placeholder: 'Text' })]),
          style === 'boxes' ? el('div', null, [input(l, 'sub', { maxlength: 80, placeholder: 'Small description' })]) : null,
          el('div', null, [linkInput(l, 'url')]),
          style === 'badges' ? el('div', { class: 'narrow' }, [select(l, 'color', ['gray', 'red', 'orange', 'yellow', 'green', 'blue'])]) : null,
          el('div', { style: 'flex:0 0 auto' }, [
            el('button', { class: 'icon', text: '▲', disabled: i === 0, onclick: function () { move(items, i, -1); draw(); } }),
            el('button', { class: 'icon danger', text: '✕', onclick: function () { items.splice(i, 1); draw(); } }),
          ]),
        ]);
        wrap.appendChild(row);
      });
      if (!items.length) wrap.appendChild(el('div', { class: 'empty', text: 'None yet.' }));
      wrap.appendChild(el('button', { text: '+ Add link', disabled: items.length >= max, onclick: function () { items.push({ label: 'New link', sub: '', url: '', color: 'gray' }); draw(); } }));
      wrap.appendChild(el('p', { class: 'hint', text: 'Links can be https://..., a page like /blog, or @email, @linkedin, @youtube, @discord... (those come from your server settings and hide themselves if not set).' }));
    }
    draw();
    return wrap;
  }

  /* ------------------------------------------------------------ site settings */
  function viewSettings(view) {
    var s = S.content.site;
    view.appendChild(el('h2', { text: 'Site Settings' }));
    view.appendChild(el('p', { class: 'sub', text: 'Things that show on every page. Changes go live when you click Save & publish.' }));
    view.appendChild(panel('Header', '', [
      el('div', { class: 'row' }, [field('Logo text', input(s, 'logo', { maxlength: 30 }, markDirty)), field('Tagline under the logo', input(s, 'tagline', { maxlength: 120 }, markDirty))]),
      el('div', { class: 'row' }, [el('div', { style: 'flex:0 0 160px' }, [field('Banner label', input(s, 'banner_label', { maxlength: 30 }, markDirty))]),
        field('Banner text', input(s, 'banner_text', { maxlength: 120 }, markDirty), '(the yellow box in the header; empty hides it)')]),
      field('Banner links to', linkInput(s, 'banner_url', markDirty), '(optional)'),
    ]));
    view.appendChild(panel('Search engines & browser', 'or', [
      field('Browser title (home page)', input(s, 'page_title', { maxlength: 80 }, markDirty)),
      field('Description for Google', input(s, 'description', { maxlength: 200 }, markDirty)),
    ]));
    view.appendChild(panel('Footer', 'bk', [field('Footer text', textarea(s, 'footer', 3, markDirty), '(each line is a new line)')]));
    view.appendChild(panel('Contact links', 'bk', [el('p', { class: 'hint', text: "Your email, LinkedIn, GitHub, Discord and SlinkGrenade links live in the server's .env file so they're in one place. Edit them there, then run: docker compose up -d" })]));
  }

  /* ------------------------------------------------------------ blog */
  function viewBlog(view) {
    view.appendChild(el('h2', { text: 'Blog' }));
    view.appendChild(el('p', { class: 'sub', text: 'Drafts are only visible here. Published posts show up on your Blog tab right away.' }));
    var holder = el('div'); view.appendChild(holder);
    holder.appendChild(el('div', { class: 'empty', text: 'Loading...' }));
    api('GET', '/api/admin/posts').then(function (r) {
      holder.textContent = '';
      if (!r.ok) { holder.appendChild(el('div', { class: 'msg', text: err(r) })); return; }
      var table = el('table', { class: 'grid' }, [el('tr', null, [el('th', { text: 'Title' }), el('th', { text: 'Status' }), el('th', { text: 'Date' }), el('th')])]);
      r.data.posts.forEach(function (p) {
        table.appendChild(el('tr', null, [
          el('td', null, [el('b', { text: p.title })]),
          el('td', null, [el('span', { class: 'tag ' + (p.published ? 'live' : 'draft'), text: p.published ? 'Published' : 'Draft' })]),
          el('td', { text: fmtTime(p.created_at) }),
          el('td', { class: 'actions' }, [
            p.published ? el('button', { text: 'View ↗', onclick: function () { site.open('/blog-post/' + p.slug); } }) : null,
            el('button', { text: 'Edit', onclick: function () { editPost(p); } }),
            el('button', { class: 'danger', text: 'Delete', onclick: function () {
              if (!confirm('Delete "' + p.title + '" forever?')) return;
              api('DELETE', '/api/admin/posts/' + p.id).then(function (d) { if (d.ok) { toast('Post deleted.'); render(); } else toast(err(d), true); });
            } }),
          ]),
        ]));
      });
      if (!r.data.posts.length) table.appendChild(el('tr', null, [el('td', { colspan: 4, class: 'empty', text: 'No posts yet. Write your first one!' })]));
      holder.appendChild(panel('Posts', '', [table], [el('button', { class: 'primary', text: '+ New post', onclick: function () { editPost(null); } })]));
    });
  }
  function editPost(p) {
    var d = p ? { title: p.title, body: p.body, published: !!p.published } : { title: '', body: '', published: false };
    var pub = el('input', { type: 'checkbox', checked: d.published });
    var body = el('div', null, [
      field('Title', input(d, 'title', { maxlength: 120 })),
      field('Post', (function () { var t = textarea(d, 'body', 16); return t; })()),
      FORMAT_HELP(),
      el('label', { class: 'check' }, [pub, 'Published (visible on the site)']),
    ]);
    modal(p ? 'Edit post' : 'New post', body, [
      { label: 'Cancel', click: closeModal },
      { label: p ? 'Save post' : 'Create post', cls: 'primary', click: function (msg) {
        d.published = pub.checked;
        api(p ? 'PUT' : 'POST', p ? '/api/admin/posts/' + p.id : '/api/admin/posts', d).then(function (r) {
          if (!r.ok) { msg.textContent = err(r); return; }
          closeModal(); toast(d.published ? 'Post is live!' : 'Draft saved.'); render();
        });
      } },
    ]);
  }

  /* ------------------------------------------------------------ pics */
  function viewPics(view) {
    view.appendChild(el('h2', { text: 'Pics' }));
    view.appendChild(el('p', { class: 'sub', text: 'Pictures for your photo album. Images are checked and converted on the server (max 10 MB).' }));
    var cap = { caption: '' };
    var up = el('div', { class: 'row' }, [field('Caption for the next upload', input(cap, 'caption', { maxlength: 60, placeholder: 'My homelab' })),
      el('div', { style: 'flex:0 0 auto' }, [el('button', { class: 'primary', text: 'Choose picture & upload...', onclick: function () {
        site.uploadPic(cap.caption).then(function (r) {
          if (r.canceled) return;
          if (!r.ok) { toast(err(r), true); return; }
          toast('Uploaded!'); render();
        });
      } })])]);
    var grid = el('div', { class: 'picgrid' }, [el('div', { class: 'empty', text: 'Loading...' })]);
    view.appendChild(panel('Upload', '', [up]));
    view.appendChild(panel('Album', 'or', [grid]));
    api('GET', '/api/pics').then(function (r) {
      grid.textContent = '';
      var pics = (r.ok && r.data.pics) || [];
      if (!pics.length) grid.appendChild(el('div', { class: 'empty', text: 'No pics yet.' }));
      pics.forEach(function (p) {
        if (!/^\/pics\/[a-f0-9]{32}\.webp$/.test(p.url)) return;
        var img = el('div', { class: 'img' }); img.style.backgroundImage = 'url("' + S.server + p.url + '")';
        grid.appendChild(el('div', { class: 'pic' }, [img, el('div', { class: 'cap', text: p.caption }),
          el('button', { class: 'danger', text: 'Delete', onclick: function () {
            if (!confirm('Delete this picture?')) return;
            api('DELETE', '/api/admin/pics/' + p.id).then(function (d) { if (d.ok) render(); else toast(err(d), true); });
          } })]));
      });
    });
  }

  /* ------------------------------------------------------------ poll */
  function viewPoll(view) {
    view.appendChild(el('h2', { text: 'Poll' }));
    view.appendChild(el('p', { class: 'sub', text: 'One poll runs at a time. Starting a new one replaces it.' }));
    var cur = el('div', null, [el('div', { class: 'empty', text: 'Loading...' })]);
    view.appendChild(panel('Current poll', '', [cur]));
    api('GET', '/api/poll').then(function (r) {
      cur.textContent = '';
      var p = r.ok && r.data.poll;
      if (!p) { cur.appendChild(el('div', { class: 'empty', text: 'No poll running.' })); return; }
      var total = p.options.reduce(function (a, o) { return a + o.votes; }, 0);
      cur.appendChild(el('b', { text: p.question }));
      p.options.forEach(function (o) {
        var pc = total ? Math.round(o.votes / total * 100) : 0, bar = el('i'); bar.style.width = pc + '%';
        cur.appendChild(el('div', { text: o.label + ' — ' + o.votes + ' vote' + (o.votes === 1 ? '' : 's') + ' (' + pc + '%)' }));
        cur.appendChild(el('div', { class: 'bar' }, [bar]));
      });
      cur.appendChild(el('div', { class: 'hint', text: total + ' total votes' }));
    });
    var d = { question: '', o: ['', '', '', '', '', ''] };
    var opts = d.o.map(function (_, i) { var x = { v: '' }; var inp = input(x, 'v', { maxlength: 60, placeholder: 'Option ' + (i + 1) + (i < 2 ? '' : ' (optional)') }); inp._x = x; return inp; });
    var msg = el('div', { class: 'msg' });
    view.appendChild(panel('Start a new poll', 'or', [field('Question', input(d, 'question', { maxlength: 120 }))].concat(
      [el('label', { text: 'Options' })], opts.map(function (o) { return el('div', { style: 'margin-bottom:5px' }, [o]); }),
      [el('button', { class: 'primary', text: 'Start poll', onclick: function () {
        var options = opts.map(function (o) { return o._x.v; }).filter(function (v) { return v.trim(); });
        api('POST', '/api/admin/poll', { question: d.question, options: options }).then(function (r) {
          if (!r.ok) { msg.className = 'msg'; msg.textContent = err(r); return; }
          toast('New poll is live!'); render();
        });
      } }), msg])));
  }

  /* ------------------------------------------------------------ shoutbox */
  function viewShouts(view) {
    view.appendChild(el('h2', { text: 'Shoutbox' }));
    view.appendChild(el('p', { class: 'sub', text: 'The latest 50 shouts. Delete anything that breaks the rules.' }));
    var table = el('table', { class: 'grid' }, [el('tr', null, [el('th', { text: 'When' }), el('th', { text: 'User' }), el('th', { text: 'Message' }), el('th')])]);
    view.appendChild(panel('Shouts', '', [table], [el('button', { text: 'Refresh', onclick: render })]));
    api('GET', '/api/shouts').then(function (r) {
      var list = ((r.ok && r.data.shouts) || []).slice().reverse();
      if (!list.length) table.appendChild(el('tr', null, [el('td', { colspan: 4, class: 'empty', text: 'No shouts yet.' })]));
      list.forEach(function (s) {
        table.appendChild(el('tr', null, [el('td', { text: fmtTime(s.at) }), el('td', null, [el('b', { text: s.user })]), el('td', { text: s.body }),
          el('td', { class: 'actions' }, [el('button', { class: 'danger', text: 'Delete', onclick: function () {
            api('DELETE', '/api/shouts/' + s.id).then(function (d) { if (d.ok) render(); else toast(err(d), true); });
          } })])]));
      });
    });
  }

  /* ------------------------------------------------------------ users */
  function viewUsers(view) {
    view.appendChild(el('h2', { text: 'Users' }));
    view.appendChild(el('p', { class: 'sub', text: 'Everyone with an account on your site.' }));
    var table = el('table', { class: 'grid' }, [el('tr', null, [el('th', { text: 'Username' }), el('th', { text: 'Joined' }), el('th', { text: 'Role' }), el('th', { text: 'Status' }), el('th')])]);
    view.appendChild(panel('Accounts', '', [table], [el('button', { text: 'Refresh', onclick: render })]));
    function act(method, path, body, done) {
      api(method, path, body).then(function (r) { if (r.ok) { toast(done); render(); } else toast(err(r), true); });
    }
    api('GET', '/api/admin/users').then(function (r) {
      ((r.ok && r.data.users) || []).forEach(function (u) {
        var me = u.username.toLowerCase() === S.name.toLowerCase();
        table.appendChild(el('tr', null, [
          el('td', null, [el('b', { text: u.username }), me ? el('span', { class: 'tag home', text: 'you' }) : null]),
          el('td', { text: new Date(u.created_at * 1000).toLocaleDateString('en-CA') }),
          el('td', { text: u.is_admin ? 'Admin' : 'Member' }),
          el('td', null, [el('span', { class: 'tag ' + (u.banned ? 'draft' : 'live'), text: u.banned ? 'Banned' : 'OK' })]),
          el('td', { class: 'actions' }, me ? [] : [
            u.is_admin ? null : el('button', { text: u.banned ? 'Unban' : 'Ban', onclick: function () {
              if (!u.banned && !confirm('Ban ' + u.username + '? Their shouts get hidden and they get logged out.')) return;
              act('POST', '/api/admin/users/' + u.id + '/ban', { banned: !u.banned }, u.banned ? 'Unbanned.' : 'Banned.');
            } }),
            el('button', { text: u.is_admin ? 'Remove admin' : 'Make admin', onclick: function () {
              if (!confirm(u.is_admin ? 'Take admin away from ' + u.username + '?' : 'Make ' + u.username + ' an admin? They will be able to change your whole site.')) return;
              act('POST', '/api/admin/users/' + u.id + '/admin', { admin: !u.is_admin }, 'Updated.');
            } }),
            el('button', { text: 'Reset password', onclick: function () { resetPassword(u); } }),
            u.is_admin ? null : el('button', { class: 'danger', text: 'Delete', onclick: function () {
              if (!confirm('Delete ' + u.username + "'s account, shouts and votes forever?")) return;
              act('DELETE', '/api/admin/users/' + u.id, undefined, 'Account deleted.');
            } }),
          ]),
        ]));
      });
    });
  }
  function resetPassword(u) {
    var d = { p1: '', p2: '' };
    modal('Reset password for ' + u.username, el('div', null, [
      el('p', { class: 'hint', text: "Set a new password and tell them what it is. They'll be logged out everywhere and can change it from My Account." }),
      field('New password', input(d, 'p1', { type: 'password', maxlength: 128, autocomplete: 'new-password' })),
      field('Type it again', input(d, 'p2', { type: 'password', maxlength: 128, autocomplete: 'new-password' })),
    ]), [
      { label: 'Cancel', click: closeModal },
      { label: 'Reset password', cls: 'primary', click: function (msg) {
        if (d.p1 !== d.p2) { msg.textContent = "Those don't match."; return; }
        api('POST', '/api/admin/users/' + u.id + '/password', { password: d.p1 }).then(function (r) {
          if (!r.ok) { msg.textContent = err(r); return; }
          closeModal(); toast('Password reset for ' + u.username + '.');
        });
      } },
    ]);
  }

  /* ------------------------------------------------------------ history */
  function viewHistory(view) {
    view.appendChild(el('h2', { text: 'History' }));
    view.appendChild(el('p', { class: 'sub', text: 'Every time pages are saved, the old version is kept (last 50). Restore one to undo changes.' }));
    var table = el('table', { class: 'grid' }, [el('tr', null, [el('th', { text: '#' }), el('th', { text: 'Saved' }), el('th', { text: 'By' }), el('th')])]);
    view.appendChild(panel('Saved versions', '', [table]));
    api('GET', '/api/admin/content/history').then(function (r) {
      ((r.ok && r.data.history) || []).forEach(function (h, i) {
        table.appendChild(el('tr', { class: h.id === S.version ? 'sel' : '' }, [
          el('td', { text: String(h.id) }), el('td', { text: fmtTime(h.saved_at) }), el('td', { text: h.saved_by }),
          el('td', { class: 'actions' }, [i === 0 ? el('span', { class: 'tag live', text: 'live now' }) : el('button', { text: 'Restore', onclick: function () {
            if (!confirm('Put your site back to how it was at ' + fmtTime(h.saved_at) + '?' + (S.dirty ? ' Your unsaved changes will be lost.' : ''))) return;
            api('POST', '/api/admin/content/history/' + h.id + '/restore').then(function (d) {
              if (!d.ok) { toast(err(d), true); return; }
              api('GET', '/api/admin/content').then(function (c) {
                S.version = c.data.version; S.content = c.data.content; S.saved = clone(c.data.content); markDirty();
                toast('Restored! Your site is back to that version.'); render();
              });
            });
          } })]),
        ]));
      });
    });
  }

  /* ------------------------------------------------------------ start */
  site.restore().then(function (r) {
    if (r.loggedIn) start(r.server, r.name); else showLogin(r.server, r.username);
  });
})();
