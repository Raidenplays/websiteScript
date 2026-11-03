plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// The app's screens are shared with the Windows app: they live in manager-app/renderer.
val sharedRenderer = file("../../manager-app/renderer")
val generatedAssets = file("build/generated/siteAssets")

val makeAndroidHtml by tasks.registering {
    val src = File(sharedRenderer, "index.html")
    inputs.file(src)
    outputs.dir(generatedAssets)
    doLast {
        val html = src.readText()
            .replace("<head>", "<head>\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
            .replace("<script src=\"app.js\"></script>", "<script src=\"bridge.js\"></script>\n  <script src=\"app.js\"></script>")
        generatedAssets.mkdirs()
        File(generatedAssets, "android.html").writeText(html)
    }
}

android {
    namespace = "com.raidenbrundin.sitemanager"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.raidenbrundin.sitemanager"
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()
        versionName = "1.0." + (System.getenv("GITHUB_RUN_NUMBER") ?: "0")
    }

    signingConfigs {
        create("release") {
            val ks = System.getenv("ANDROID_KEYSTORE_FILE")
            if (ks != null && File(ks).exists()) {
                storeFile = File(ks)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            } else {
                // Shared key so every build can install over the last one. See README to use your own.
                storeFile = file("release.keystore")
                storePassword = "raidensite"
                keyAlias = "raidensite"
                keyPassword = "raidensite"
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }

    sourceSets["main"].assets.srcDirs("src/main/assets", sharedRenderer, generatedAssets)

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

tasks.named("preBuild") { dependsOn(makeAndroidHtml) }

dependencies {
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.documentfile:documentfile:1.0.1")
}
