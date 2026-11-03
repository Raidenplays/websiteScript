// The only bridge between the window and the main process.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('site', {
  api: (method, path, body) => ipcRenderer.invoke('api', { method, path, body }),
  login: (o) => ipcRenderer.invoke('login', o),
  restore: () => ipcRenderer.invoke('restore'),
  logout: () => ipcRenderer.invoke('logout'),
  open: (p) => ipcRenderer.invoke('open', p),
  uploadPic: (caption) => ipcRenderer.invoke('uploadPic', { caption }),
  setDirty: (d) => ipcRenderer.send('dirty', !!d),
});
