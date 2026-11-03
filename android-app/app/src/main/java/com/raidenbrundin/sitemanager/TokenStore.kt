package com.raidenbrundin.sitemanager

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Remembers the site address and username, and (if asked) the login token encrypted with an Android Keystore key. */
class TokenStore(context: Context) {
    private val prefs = context.getSharedPreferences("site_manager", Context.MODE_PRIVATE)

    fun server(): String? = prefs.getString("server", null)
    fun user(): String? = prefs.getString("user", null)

    fun save(server: String, user: String, token: String?) {
        val edit = prefs.edit().putString("server", server).putString("user", user)
        if (token == null) {
            edit.remove("token")
        } else {
            val cipher = Cipher.getInstance(TRANSFORM)
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val enc = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
            edit.putString("token", b64(cipher.iv) + ":" + b64(enc))
        }
        edit.apply()
    }

    fun token(): String? = try {
        val parts = prefs.getString("token", null)?.split(":")
        if (parts == null || parts.size != 2) {
            null
        } else {
            val cipher = Cipher.getInstance(TRANSFORM)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, unb64(parts[0])))
            String(cipher.doFinal(unb64(parts[1])), Charsets.UTF_8)
        }
    } catch (_: Exception) {
        null
    }

    fun clearToken() {
        prefs.edit().remove("token").apply()
    }

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return gen.generateKey()
    }

    private fun b64(b: ByteArray) = Base64.encodeToString(b, Base64.NO_WRAP)
    private fun unb64(s: String) = Base64.decode(s, Base64.NO_WRAP)

    companion object {
        private const val ALIAS = "site_manager_token"
        private const val TRANSFORM = "AES/GCM/NoPadding"
    }
}
