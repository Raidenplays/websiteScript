package com.raidenbrundin.sitemanager

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import androidx.documentfile.provider.DocumentFile
import org.json.JSONArray
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.Executors

/**
 * Native side of `window.site` (see assets/bridge.js). Does every network request itself and keeps the
 * login token here, so the page never sees it. Mirrors manager-app/main.js on Windows.
 */
class Bridge(
    private val activity: Activity,
    private val web: WebView,
    private val launchPicker: () -> Unit,
    private val launchFilePicker: (Array<String>) -> Unit,
    private val launchFolderPicker: () -> Unit,
) {
    private val exec = Executors.newFixedThreadPool(3)
    private val store = TokenStore(activity)

    @Volatile private var server: String? = null
    @Volatile private var token: String? = null
    @Volatile var dirty = false
        private set
    private var pendingUpload: Pair<Int, String>? = null
    /** A file/zip/folder pick that's waiting for the user: which call, and what it asked for. */
    private data class Pick(val id: Int, val kind: String, val name: String, val replace: Boolean, val folder: String)
    private var pendingPick: Pick? = null

    @JavascriptInterface
    fun setDirty(value: Boolean) {
        dirty = value
    }

    @JavascriptInterface
    fun call(id: Int, name: String, argsJson: String) {
        val args = try { JSONObject(argsJson) } catch (e: Exception) { JSONObject() }
        if (name == "uploadFile" || name == "uploadZip" || name == "uploadFolder") {
            activity.runOnUiThread {
                pendingPick?.let { resolve(it.id, JSONObject().put("canceled", true)) }
                pendingPick = Pick(id, name, args.optString("name").take(100), args.optBoolean("replace"), cleanFolder(args.optString("folder")))
                when (name) {
                    "uploadFile" -> launchFilePicker(arrayOf("*/*"))
                    "uploadZip" -> launchFilePicker(arrayOf("application/zip", "application/x-zip-compressed", "application/octet-stream"))
                    else -> launchFolderPicker()
                }
            }
            return
        }
        if (name == "uploadPic") {
            activity.runOnUiThread {
                pendingUpload?.let { resolve(it.first, JSONObject().put("canceled", true)) }
                pendingUpload = id to args.optString("caption").take(60)
                launchPicker()
            }
            return
        }
        exec.execute {
            val result: Any = try {
                when (name) {
                    "api" -> request(args.optString("method", "GET"), args.optString("path"), if (args.has("body")) args.get("body") else null)
                    "login" -> login(args)
                    "restore" -> restore()
                    "logout" -> logout()
                    "open" -> openInBrowser(args.optString("path"))
                    else -> fail(0, "Unknown action.")
                }
            } catch (e: Exception) {
                fail(0, "Something went wrong: ${e.message}")
            }
            resolve(id, result)
        }
    }

    fun onImagePicked(uri: Uri?) {
        val (id, caption) = pendingUpload ?: return
        pendingUpload = null
        if (uri == null) {
            resolve(id, JSONObject().put("canceled", true))
            return
        }
        exec.execute {
            resolve(id, try { uploadPic(uri, caption) } catch (e: Exception) { fail(0, "Couldn't upload that picture: ${e.message}") })
        }
    }

    fun onFilePicked(uri: Uri?) = onPicked(uri)
    fun onFolderPicked(uri: Uri?) = onPicked(uri)

    private fun onPicked(uri: Uri?) {
        val pick = pendingPick ?: return
        pendingPick = null
        if (uri == null) {
            resolve(pick.id, JSONObject().put("canceled", true))
            return
        }
        exec.execute {
            resolve(pick.id, try {
                when (pick.kind) {
                    "uploadFile" -> uploadFile(uri, pick.name, pick.replace, pick.folder)
                    "uploadZip" -> uploadZip(uri, pick)
                    else -> uploadFolder(uri, pick)
                }
            } catch (e: Exception) {
                fail(0, "Upload failed: ${e.message}")
            })
        }
    }

    fun shutdown() = exec.shutdownNow()

    // ------------------------------------------------------------------ actions

    private fun normServer(raw: String): String {
        var s = raw.trim().lowercase().removeSuffix("/")
        s = s.removePrefix("https://").removePrefix("http://")
        if (!Regex("[a-z0-9.-]+(:[0-9]{1,5})?").matches(s)) throw IllegalArgumentException("Enter your site address, like raidenbrundin.com")
        return "https://$s"
    }

    private fun login(a: JSONObject): JSONObject {
        server = try { normServer(a.optString("server")) } catch (e: IllegalArgumentException) { return fail(0, e.message ?: "Bad address.") }
        token = null
        val r = request("POST", "/api/app/login", JSONObject().put("username", a.optString("username")).put("password", a.optString("password")))
        if (!r.optBoolean("ok")) return r
        val data = r.getJSONObject("data")
        token = data.getString("token")
        store.save(server!!, a.optString("username"), if (a.optBoolean("remember")) token else null)
        return JSONObject().put("ok", true).put("data", JSONObject().put("name", data.optString("name")).put("server", server))
    }

    private fun restore(): JSONObject {
        val savedServer = store.server()
        val savedToken = store.token()
        if (savedServer != null && savedToken != null) {
            server = savedServer
            token = savedToken
            val r = request("GET", "/api/me", null)
            val user = r.optJSONObject("data")?.optJSONObject("user")
            if (r.optBoolean("ok") && user != null && user.optBoolean("admin")) {
                return JSONObject().put("loggedIn", true).put("server", savedServer).put("name", user.optString("name"))
            }
            token = null
            if (r.optInt("status") == 401) store.clearToken()
        }
        return JSONObject().put("loggedIn", false)
            .put("server", savedServer ?: "https://raidenbrundin.com")
            .put("username", store.user() ?: "")
    }

    private fun logout(): Boolean {
        if (token != null) request("POST", "/api/logout", JSONObject())
        token = null
        store.clearToken()
        return true
    }

    private fun openInBrowser(path: String): Boolean {
        val s = server ?: return false
        val rel = if (Regex("/[A-Za-z0-9/_.#-]*").matches(path)) path else "/"
        activity.runOnUiThread {
            try { activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(s + rel))) } catch (_: Exception) { }
        }
        return true
    }

    private fun uploadPic(uri: Uri, caption: String): JSONObject {
        val resolver = activity.contentResolver
        val mime = resolver.getType(uri) ?: "image/jpeg"
        if (mime !in setOf("image/png", "image/jpeg", "image/gif", "image/webp")) return fail(0, "Only PNG, JPG, GIF or WEBP pictures.")
        val bytes = resolver.openInputStream(uri)?.use { input ->
            val out = ByteArrayOutputStream()
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                out.write(buf, 0, n)
                if (out.size() > MAX_UPLOAD) return fail(0, "That picture is too big (max 10 MB).")
            }
            out.toByteArray()
        } ?: return fail(0, "Couldn't open that picture.")
        val ext = when (mime) { "image/png" -> "png"; "image/gif" -> "gif"; "image/webp" -> "webp"; else -> "jpg" }
        val cleanCaption = caption.replace(Regex("[\\r\\n\"]"), " ")
        val boundary = "----RaidenSite" + UUID.randomUUID().toString().replace("-", "")
        val body = ByteArrayOutputStream().apply {
            write(("--$boundary\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n$cleanCaption\r\n").toByteArray())
            write(("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"photo.$ext\"\r\nContent-Type: $mime\r\n\r\n").toByteArray())
            write(bytes)
            write(("\r\n--$boundary--\r\n").toByteArray())
        }.toByteArray()
        return send("POST", "/api/admin/pics", body, "multipart/form-data; boundary=$boundary")
    }

    private fun displayName(uri: Uri): String =
        activity.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) c.getString(0) else null
        } ?: "file"

    /** Reads the whole file, or returns null if it's bigger than [max]. */
    private fun readLimited(uri: Uri, max: Int): ByteArray? {
        val input = activity.contentResolver.openInputStream(uri) ?: throw IOException("Couldn't open the file")
        return input.use {
            val out = ByteArrayOutputStream()
            val buf = ByteArray(64 * 1024)
            var tooBig = false
            while (true) {
                val n = it.read(buf)
                if (n < 0) break
                out.write(buf, 0, n)
                if (out.size() > max) { tooBig = true; break }
            }
            if (tooBig) null else out.toByteArray()
        }
    }

    private fun cleanFolder(f: String): String =
        f.replace('\\', '/').split('/').filter { it.isNotBlank() }.joinToString("/").take(300)

    private fun safeSeg(n: String): String =
        n.replace(Regex("[^A-Za-z0-9._ ()~-]"), "-").replace(Regex("^[^A-Za-z0-9]+"), "").replace(Regex("[. ]+$"), "").take(100).ifEmpty { "folder" }

    private fun progress(text: String) {
        web.post { web.evaluateJavascript("window.__siteProgress && window.__siteProgress(${JSONObject.quote(text)})", null) }
    }

    private fun multipart(fields: List<Pair<String, String>>, fileName: String, mime: String, bytes: ByteArray): Pair<ByteArray, String> {
        val boundary = "----RaidenSite" + UUID.randomUUID().toString().replace("-", "")
        val safeName = fileName.replace(Regex("[\\r\\n\"/\\\\]"), "_").take(150)
        val body = ByteArrayOutputStream().apply {
            for ((k, v) in fields) {
                write(("--$boundary\r\nContent-Disposition: form-data; name=\"$k\"\r\n\r\n${v.replace(Regex("[\\r\\n]"), " ")}\r\n").toByteArray())
            }
            write(("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"$safeName\"\r\nContent-Type: $mime\r\n\r\n").toByteArray())
            write(bytes)
            write(("\r\n--$boundary--\r\n").toByteArray())
        }.toByteArray()
        return body to "multipart/form-data; boundary=$boundary"
    }

    private fun uploadFile(uri: Uri, saveAs: String, replace: Boolean, folder: String): JSONObject {
        val bytes = readLimited(uri, MAX_FILE) ?: return fail(0, "That file is too big (max 25 MB).")
        val (body, type) = multipart(
            listOf("name" to saveAs, "replace" to (if (replace) "1" else "0"), "folder" to folder),
            displayName(uri), "application/octet-stream", bytes,
        )
        return send("POST", "/api/admin/files", body, type)
    }

    private fun uploadZip(uri: Uri, pick: Pick): JSONObject {
        val bytes = readLimited(uri, MAX_FILE) ?: return fail(0, "That .zip is too big (max 25 MB).")
        val fname = displayName(uri)
        val name = safeSeg(pick.name.trim().ifEmpty { fname.replace(Regex("(?i)\\.zip$"), "") })
        val dest = if (pick.folder.isEmpty()) name else "${pick.folder}/$name"
        progress("Uploading and unpacking...")
        val (body, type) = multipart(listOf("folder" to dest, "replace" to (if (pick.replace) "1" else "0")), fname, "application/zip", bytes)
        return send("POST", "/api/admin/files/zip", body, type)
    }

    private fun uploadFolder(treeUri: Uri, pick: Pick): JSONObject {
        val root = DocumentFile.fromTreeUri(activity, treeUri) ?: return fail(0, "Couldn't open that folder.")
        val name = safeSeg(pick.name.trim().ifEmpty { root.name ?: "folder" })
        val dest = if (pick.folder.isEmpty()) name else "${pick.folder}/$name"
        val found = mutableListOf<Pair<DocumentFile, String>>()
        fun walk(dir: DocumentFile, rel: String, depth: Int) {
            if (depth > 5 || found.size > 1000) return
            for (f in dir.listFiles()) {
                val n = f.name ?: continue
                if (n.startsWith(".")) continue
                val r = if (rel.isEmpty()) n else "$rel/$n"
                if (f.isDirectory) walk(f, r, depth + 1) else if (f.isFile) found.add(f to r)
            }
        }
        walk(root, "", 0)
        if (found.size > 1000) return fail(0, "That folder has more than 1000 files.")
        var uploaded = 0
        var total = 0L
        val skipped = JSONArray()
        for ((i, pair) in found.withIndex()) {
            val (doc, rel) = pair
            val ext = rel.substringAfterLast('.', "").lowercase()
            if (ext !in ALLOWED_EXTS) { skipped.put("$rel (file type)"); continue }
            val bytes = readLimited(doc.uri, MAX_FILE)
            if (bytes == null) { skipped.put("$rel (too big)"); continue }
            total += bytes.size
            if (total > 150L * 1024 * 1024) { skipped.put("...stopped: over 150 MB"); break }
            progress("Uploading ${i + 1} of ${found.size}: $rel")
            val sub = rel.substringBeforeLast('/', "")
            val (body, type) = multipart(
                listOf("folder" to (if (sub.isEmpty()) dest else "$dest/$sub"), "keep_name" to "1", "replace" to "1"),
                doc.name ?: "file", "application/octet-stream", bytes,
            )
            val r = send("POST", "/api/admin/files", body, type)
            if (r.optBoolean("ok")) uploaded++
            else skipped.put("$rel: " + (r.optJSONObject("data")?.optString("error") ?: "failed"))
        }
        val data = JSONObject().put("folder", dest).put("uploaded", uploaded).put("skipped", skipped)
        if (uploaded == 0) data.put("error", "Nothing in that folder could be uploaded.")
        return JSONObject().put("ok", uploaded > 0).put("status", 200).put("data", data)
    }

    // ------------------------------------------------------------------ http

    private fun request(method: String, path: String, body: Any?): JSONObject {
        val payload = if (body == null || body == JSONObject.NULL) null else body.toString().toByteArray()
        return send(method, path, payload, if (payload != null) "application/json" else null)
    }

    private fun send(method: String, path: String, payload: ByteArray?, contentType: String?): JSONObject {
        val first = sendOnce(method, path, payload, contentType)
        // A phone switching networks can drop one request; safely retry reads once.
        return if (first.optInt("status") == 0 && method.uppercase() == "GET" && server != null) sendOnce(method, path, payload, contentType) else first
    }

    private fun sendOnce(method: String, path: String, payload: ByteArray?, contentType: String?): JSONObject {
        val base = server ?: return fail(0, "Not connected.")
        val m = method.uppercase()
        if (!path.startsWith("/api/") || m !in setOf("GET", "POST", "PUT", "DELETE")) return fail(0, "Bad request.")
        val conn = URL(base + path).openConnection() as HttpURLConnection
        return try {
            conn.requestMethod = m
            conn.connectTimeout = 15_000
            conn.readTimeout = 60_000
            conn.instanceFollowRedirects = false
            conn.useCaches = false
            conn.setRequestProperty("Accept", "application/json")
            token?.let { conn.setRequestProperty("Authorization", "Bearer $it") }
            if (payload != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", contentType)
                conn.setFixedLengthStreamingMode(payload.size)
                conn.outputStream.use { it.write(payload) }
            }
            val code = conn.responseCode
            val text = (if (code >= 400) conn.errorStream else conn.inputStream)?.bufferedReader()?.use { it.readText() } ?: ""
            val data = try { JSONObject(text) } catch (_: Exception) { JSONObject() }
            JSONObject().put("ok", code in 200..299).put("status", code).put("data", data)
        } catch (e: IOException) {
            // Show the real reason too, so problems can be tracked down.
            fail(0, "Couldn't reach $base. Check your internet connection and try again.\n(${e.javaClass.simpleName}: ${e.message ?: "no details"})")
        } finally {
            conn.disconnect()
        }
    }

    private fun fail(status: Int, msg: String): JSONObject =
        JSONObject().put("ok", false).put("status", status).put("data", JSONObject().put("error", msg))

    private fun resolve(id: Int, value: Any) {
        val json = value.toString()
        web.post { web.evaluateJavascript("window.__siteResolve($id, ${JSONObject.quote(json)})", null) }
    }

    companion object {
        private const val MAX_UPLOAD = 10 * 1024 * 1024
        private const val MAX_FILE = 25 * 1024 * 1024
        private val ALLOWED_EXTS = setOf(
            "pdf", "html", "htm", "css", "js", "json", "txt", "md", "csv", "png", "jpg", "jpeg", "gif", "webp", "svg", "ico",
            "woff", "woff2", "ttf", "otf", "mp3", "wav", "ogg", "mp4", "webm", "zip", "docx", "xlsx", "pptx", "odt",
        )
    }
}
