/* Android version of window.site: forwards every call to the native Bridge (Bridge.kt). */
(function () {
  'use strict';
  var pending = {}, next = 1;
  window.__siteResolve = function (id, json) {
    var done = pending[id]; if (!done) return;
    delete pending[id];
    var v;
    try { v = JSON.parse(json); } catch (e) { v = { ok: false, status: 0, data: { error: 'Bad response from the app.' } }; }
    done(v);
  };
  function call(name, args) {
    return new Promise(function (res) {
      var id = next++;
      pending[id] = res;
      window.AndroidSite.call(id, name, JSON.stringify(args || {}));
    });
  }
  window.site = {
    api: function (method, path, body) { var a = { method: method, path: path }; if (body !== undefined) a.body = body; return call('api', a); },
    login: function (o) { return call('login', o); },
    restore: function () { return call('restore'); },
    logout: function () { return call('logout'); },
    open: function (p) { return call('open', { path: p }); },
    uploadPic: function (caption) { return call('uploadPic', { caption: caption }); },
    uploadFile: function (o) { return call('uploadFile', { name: (o && o.name) || '', replace: !!(o && o.replace), folder: (o && o.folder) || '' }); },
    uploadZip: function (o) { return call('uploadZip', { name: (o && o.name) || '', replace: !!(o && o.replace), folder: (o && o.folder) || '' }); },
    uploadFolder: function (o) { return call('uploadFolder', { name: (o && o.name) || '', folder: (o && o.folder) || '' }); },
    onProgress: function (cb) { window.__siteProgress = cb; },
    setDirty: function (d) { window.AndroidSite.setDirty(!!d); },
  };
  document.documentElement.className += ' android';
})();
