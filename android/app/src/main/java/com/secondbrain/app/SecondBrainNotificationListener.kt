package com.secondbrain.app

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class SecondBrainNotificationListener : NotificationListenerService() {
    companion object {
        fun requestActiveSync(context: android.content.Context) {
            requestRebind(android.content.ComponentName(context, SecondBrainNotificationListener::class.java))
        }
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        getSharedPreferences("second_brain", MODE_PRIVATE).edit()
            .putLong("notification_listener_connected_at", System.currentTimeMillis()).apply()
        syncActiveNotifications()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        ingest(sbn)
    }

    private fun syncActiveNotifications() {
        activeNotifications?.forEach(::ingest)
    }

    private fun ingest(sbn: StatusBarNotification) {
        val extras = sbn.notification.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        // MessagingStyle and several system apps put their useful content in
        // BIG_TEXT or TEXT_LINES rather than EXTRA_TEXT.
        val text = sequenceOf(
            extras.getCharSequence(Notification.EXTRA_TEXT)?.toString(),
            extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString(),
            extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)?.joinToString("\n") { it.toString() },
            extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString(),
        ).firstOrNull { !it.isNullOrBlank() }.orEmpty()
        if (title.isBlank() && text.isBlank()) return
        val preferences = getSharedPreferences("second_brain", MODE_PRIVATE)
        val server = preferences.getString("server", null) ?: return
        val token = preferences.getString("access_token", null) ?: return
        val fingerprint = "${sbn.key}:${sbn.postTime}"
        val seen = preferences.getStringSet("notification_seen", emptySet()).orEmpty()
        if (fingerprint in seen) return
        preferences.edit().putStringSet("notification_seen", (seen + fingerprint).toList().takeLast(250).toSet()).apply()
        preferences.edit().putLong("notification_last_captured_at", System.currentTimeMillis()).apply()
        SyncWorker.enqueueNotification(this, server, token, sbn.packageName, title, text.ifBlank { title })
    }
}
