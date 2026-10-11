package com.secondbrain.app

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class SecondBrainNotificationListener : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val extras = sbn.notification.extras
        val title = extras.getCharSequence("android.title")?.toString() ?: ""
        val text = extras.getCharSequence("android.text")?.toString() ?: return
        val preferences = getSharedPreferences("second_brain", MODE_PRIVATE)
        val server = preferences.getString("server", null) ?: return
        val token = preferences.getString("access_token", null) ?: return
        SyncWorker.enqueueNotification(this, server, token, sbn.packageName, title, text)
    }
}
