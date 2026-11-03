# Raiden Site Manager

Windows app for editing raidenbrundin.com: pages and sections, blog, pics, poll, shoutbox, users and history.

It's an Electron app. `main.js` does all the talking to the server, `preload.js` is the bridge, and `renderer/` is the window.

## Run from source
```
npm install
npm start
```

## Build the Windows version
```
npm run build:win
```
The app ends up in `dist/Raiden Site Manager-win32-x64/`. To give the .exe your own icon, build it on Windows; on Linux that step needs Wine.
