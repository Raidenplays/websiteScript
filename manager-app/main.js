// Raiden Site Manager - main process.
// All network requests happen here; the window only talks to this file through preload.js.
const { app, BrowserWindow, ipcMain, shell, dialog, safeStorage } = require('electron');
const path = require('path');
const fs = require('fs');

let win = null;
let server = null; // e.g. https://raidenbrundin.com
let token = null;  // admin session token (never given to the window)
let dirty = false;

const settingsPath = () => path.join(app.getPath('userData'), 'settings.json');
function loadSettings() { try { return JSON.parse(fs.readFileSync(settingsPath(), 'utf8')); } catch { return {}; } }
function saveSettings(s) { try { fs.writeFileSync(settingsPath(), JSON.stringify(s)); } catch { /* ignore */ } }

function normServer(u) {
  u = String(u || '').trim().replace(/\/+$/, '');
  if (!/^https:\/\//i.test(u) && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(u)) u = 'https://' + u.replace(/^http:\/\//i, '');
  if (!/^https:\/\/[a-z0-9.-]+(:\d+)?$/i.test(u) && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(u)) {
    throw new Error('Enter your site address, like raidenbrundin.com');
  }
  return u.toLowerCase();
}

async function request(method, p, body, isForm) {
  if (!server) return { ok: false, status: 0, data: { error: 'Not connected.' } };
  if (typeof p !== 'string' || !p.startsWith('/api/')) return { ok: false, status: 0, data: { error: 'Bad request.' } };
  const headers = {};
  if (token) headers.Authorization = 'Bearer ' + token;
  let payload;
  if (isForm) payload = body;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  let r;
  try {
    r = await fetch(server + p, { method, headers, body: payload, redirect: 'error', signal: AbortSignal.timeout(30000) });
  } catch {
    return { ok: false, status: 0, data: { error: "Couldn't reach " + server + '. Check the address and your internet connection.' } };
  }
  let data = {};
  try { data = await r.json(); } catch { /* not JSON */ }
  return { ok: r.ok, status: r.status, data };
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 840, minWidth: 1040, minHeight: 640,
    title: 'Raiden Site Manager', backgroundColor: '#1d1d1d', show: false,
    icon: path.join(__dirname, 'renderer', 'icon.png'),
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  win.removeMenu();
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.once('ready-to-show', () => win.show());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  win.on('close', (e) => {
    if (!dirty) return;
    const choice = dialog.showMessageBoxSync(win, {
      type: 'warning', buttons: ['Close without saving', 'Cancel'], defaultId: 1, cancelId: 1,
      title: 'Unsaved changes', message: "You have changes that aren't saved yet.", detail: 'Close anyway and lose them?',
    });
    if (choice !== 0) e.preventDefault();
  });
}

ipcMain.handle('api', (_e, a) => request(String(a.method || 'GET').toUpperCase(), a.path, a.body));

ipcMain.handle('login', async (_e, a) => {
  try { server = normServer(a.server); } catch (err) { return { ok: false, data: { error: err.message } }; }
  token = null;
  const r = await request('POST', '/api/app/login', { username: String(a.username || ''), password: String(a.password || '') });
  if (r.ok) {
    token = r.data.token;
    const st = loadSettings();
    st.server = server; st.username = a.username;
    if (a.remember && safeStorage.isEncryptionAvailable()) st.token = safeStorage.encryptString(token).toString('base64');
    else delete st.token;
    saveSettings(st);
    return { ok: true, data: { name: r.data.name, server } };
  }
  return r;
});

ipcMain.handle('restore', async () => {
  const st = loadSettings();
  if (st.server && st.token && safeStorage.isEncryptionAvailable()) {
    try {
      server = st.server;
      token = safeStorage.decryptString(Buffer.from(st.token, 'base64'));
      const r = await request('GET', '/api/me');
      if (r.ok && r.data.user && r.data.user.admin) return { loggedIn: true, server, name: r.data.user.name };
    } catch { /* fall through */ }
    token = null;
    delete st.token; saveSettings(st);
  }
  return { loggedIn: false, server: st.server || 'https://raidenbrundin.com', username: st.username || '' };
});

ipcMain.handle('logout', async () => {
  if (token) await request('POST', '/api/logout', {});
  token = null;
  const st = loadSettings(); delete st.token; saveSettings(st);
  return true;
});

ipcMain.handle('open', (_e, p) => {
  if (!server) return;
  const rel = typeof p === 'string' && /^\/[A-Za-z0-9/_.#-]*$/.test(p) ? p : '/';
  shell.openExternal(server + rel);
});

ipcMain.handle('uploadPic', async (_e, a) => {
  const res = await dialog.showOpenDialog(win, {
    title: 'Pick a picture to upload', properties: ['openFile'],
    filters: [{ name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp'] }],
  });
  if (res.canceled || !res.filePaths[0]) return { canceled: true };
  const fp = res.filePaths[0];
  if (fs.statSync(fp).size > 10 * 1024 * 1024) return { ok: false, data: { error: 'That file is too big (max 10 MB).' } };
  const fd = new FormData();
  fd.append('file', new Blob([fs.readFileSync(fp)]), path.basename(fp));
  fd.append('caption', String((a && a.caption) || '').slice(0, 60));
  return request('POST', '/api/admin/pics', fd, true);
});

const FILE_EXTS = ['pdf', 'html', 'htm', 'txt', 'md', 'csv', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp3', 'mp4', 'zip', 'docx', 'xlsx', 'pptx', 'odt'];
ipcMain.handle('uploadFile', async (_e, a) => {
  const res = await dialog.showOpenDialog(win, {
    title: 'Pick a file to upload', properties: ['openFile'],
    filters: [{ name: 'Allowed files', extensions: FILE_EXTS }],
  });
  if (res.canceled || !res.filePaths[0]) return { canceled: true };
  const fp = res.filePaths[0];
  if (fs.statSync(fp).size > 25 * 1024 * 1024) return { ok: false, data: { error: 'That file is too big (max 25 MB).' } };
  const fd = new FormData();
  fd.append('file', new Blob([fs.readFileSync(fp)]), path.basename(fp));
  fd.append('name', String((a && a.name) || '').slice(0, 100));
  fd.append('replace', a && a.replace ? '1' : '0');
  return request('POST', '/api/admin/files', fd, true);
});

ipcMain.on('dirty', (_e, d) => { dirty = !!d; });

app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());
