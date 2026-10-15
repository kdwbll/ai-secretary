plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }

val releaseKeystorePath = System.getenv("SECOND_BRAIN_KEYSTORE_PATH")
val releaseStorePassword = System.getenv("SECOND_BRAIN_KEYSTORE_PASSWORD")
val releaseKeyAlias = System.getenv("SECOND_BRAIN_KEY_ALIAS")
val releaseKeyPassword = System.getenv("SECOND_BRAIN_KEY_PASSWORD")
val hasReleaseSigning = listOf(releaseKeystorePath, releaseStorePassword, releaseKeyAlias, releaseKeyPassword).all { !it.isNullOrBlank() }

android {
    namespace = "com.secondbrain.app"
    compileSdk = 35
    defaultConfig { applicationId = "com.secondbrain.app"; minSdk = 28; targetSdk = 35; versionCode = 26; versionName = "0.15.1" }
    signingConfigs {
        if (hasReleaseSigning) create("stableRelease") {
            storeFile = file(releaseKeystorePath!!)
            storePassword = releaseStorePassword
            keyAlias = releaseKeyAlias
            keyPassword = releaseKeyPassword
        }
    }
    buildTypes {
        getByName("release") {
            if (hasReleaseSigning) signingConfig = signingConfigs.getByName("stableRelease")
            isMinifyEnabled = false
        }
    }
    buildFeatures { compose = true; buildConfig = true }
    composeOptions { kotlinCompilerExtensionVersion = "1.5.15" }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.09.03"))
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    implementation("androidx.health.connect:connect-client:1.1.0-alpha11")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
