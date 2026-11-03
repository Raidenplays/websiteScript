package com.raidenbrundin.sitemanager

import android.app.AlertDialog
import android.os.Bundle
import android.webkit.JsResult
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.webkit.WebViewAssetLoader

/**
 * Hosts the shared Site Manager screens (the same ones the Windows app uses) in a locked-down WebView.
 * Everything that touches the network, the saved login or the photo picker happens in [Bridge].
 */
class MainActivity : ComponentActivity() {

    private lateinit var web: WebView
    private lateinit var bridge: Bridge

    private val pickImage = registerForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        bridge.onImagePicked(uri)
    }

    private val pickFile = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        bridge.onFilePicked(uri)
    }

    private val pickFolder = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        bridge.onFolderPicked(uri)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        web = WebView(this)
        setContentView(web)

        // Serves the app's own files from https://appassets.androidplatform.net/assets/...
        val assets = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = false
            allowFileAccess = false
            allowContentAccess = false
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)
            setSupportZoom(false)
        }

        bridge = Bridge(
            this, web,
            launchPicker = { pickImage.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
            launchFilePicker = { types -> pickFile.launch(types) },
            launchFolderPicker = { pickFolder.launch(null) },
        )
        web.addJavascriptInterface(bridge, "AndroidSite")

        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                assets.shouldInterceptRequest(request.url)

            // The window never navigates anywhere else; links to the site open in the browser instead.
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean = true
        }

        web.webChromeClient = object : WebChromeClient() {
            override fun onJsConfirm(view: WebView, url: String?, message: String?, result: JsResult): Boolean {
                AlertDialog.Builder(this@MainActivity)
                    .setMessage(message)
                    .setPositiveButton(android.R.string.ok) { _, _ -> result.confirm() }
                    .setNegativeButton(android.R.string.cancel) { _, _ -> result.cancel() }
                    .setOnCancelListener { result.cancel() }
                    .show()
                return true
            }

            override fun onJsAlert(view: WebView, url: String?, message: String?, result: JsResult): Boolean {
                AlertDialog.Builder(this@MainActivity)
                    .setMessage(message)
                    .setPositiveButton(android.R.string.ok) { _, _ -> result.confirm() }
                    .setOnCancelListener { result.confirm() }
                    .show()
                return true
            }
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                // Let the screens close a dialog or go back to Pages first.
                web.evaluateJavascript("window.__siteBack ? window.__siteBack() : false") { handled ->
                    if (handled == "true") return@evaluateJavascript
                    if (bridge.dirty) {
                        AlertDialog.Builder(this@MainActivity)
                            .setTitle("Unsaved changes")
                            .setMessage("You have changes that aren't saved yet. Leave anyway and lose them?")
                            .setPositiveButton("Leave") { _, _ -> finish() }
                            .setNegativeButton(android.R.string.cancel, null)
                            .show()
                    } else {
                        finish()
                    }
                }
            }
        })

        web.loadUrl("https://appassets.androidplatform.net/assets/android.html")
    }

    override fun onDestroy() {
        bridge.shutdown()
        web.destroy()
        super.onDestroy()
    }
}
