# Android release signing

Android upgrades require every APK to use the same signing key. The private key must never be committed to this public repository.

The Android release workflow requires these GitHub Actions repository secrets:

- `ANDROID_KEYSTORE_BASE64`: base64-encoded JKS file, with no line wrapping.
- `ANDROID_KEYSTORE_PASSWORD`: JKS password.
- `ANDROID_KEY_ALIAS`: signing key alias.
- `ANDROID_KEY_PASSWORD`: signing key password.

The workflow deliberately fails before building when any secret is absent. It builds `assembleRelease`, verifies the APK signature, and uploads only that signed release APK.

Back up the original JKS and passwords in at least two secure locations. Losing the key makes in-place upgrades impossible. Rotating the key outside an app-store-managed key rotation also requires users to uninstall the previous app.

For a local signed build, set the equivalent `SECOND_BRAIN_*` environment variables and run:

```sh
cd android
./gradlew assembleRelease
```

The output is `android/app/build/outputs/apk/release/app-release.apk`.
