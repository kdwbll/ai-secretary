package com.secondbrain.app

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class SecondBrainNotificationListener : NotificationListenerService() {
    override fun onListenerConnected() {
        super.onListenerConnected()
        getSharedPreferences("second_brain", MODE_PRIVATE).edit()
            .putLong("notification_listener_connected_at", System.currentTimeMillis()).apply()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
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
        preferences.edit().putLong("notification_last_captured_at", System.currentTimeMillis()).apply()
        SyncWorker.enqueueNotification(this, server, token, sbn.packageName, title, text.ifBlank { title })
    }
}
