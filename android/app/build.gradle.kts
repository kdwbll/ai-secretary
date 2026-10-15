plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }

android {
    namespace = "com.secondbrain.app"
    compileSdk = 35
    defaultConfig { applicationId = "com.secondbrain.app"; minSdk = 28; targetSdk = 35; versionCode = 25; versionName = "0.15.0" }
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
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
