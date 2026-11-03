# Site Manager for Android

The Android version of Raiden Site Manager. It uses the **same screens as the Windows app** (`../manager-app/renderer`), so both always have the same features. The Android-only parts are in Kotlin:

- `MainActivity.kt`: a locked-down WebView that can't navigate anywhere else, plus the Back button and confirm dialogs
- `Bridge.kt`: does all the network requests and keeps the login token, so the page never sees it
- `TokenStore.kt`: "Keep me logged in" encrypts the token with an Android Keystore key

## Getting the app
GitHub builds it automatically whenever this folder or the shared screens change.
Install the latest version on your phone from:
https://github.com/Raidenplays/websiteScript/releases/latest/download/RaidenSiteManager.apk

## Signing
Builds are signed with `app/release.keystore`, so every new version installs over the old one.
Because this repo is public, anyone could sign an APK with that key. Only install the app from this repo's Releases page.
To use a private key instead, add these repo secrets: `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`.
Switching keys means uninstalling the old app once.
