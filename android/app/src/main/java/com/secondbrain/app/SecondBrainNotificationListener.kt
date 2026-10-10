package com.secondbrain.app

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class SecondBrainNotificationListener : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val extras = sbn.notification.extras
        val title = extras.getCharSequence("android.title")?.toString() ?: ""
        val text = extras.getCharSequence("android.text")?.toString() ?: return
        val server = getSharedPreferences("second_brain", MODE_PRIVATE).getString("server", null) ?: return
        SyncWorker.enqueueNotification(this, server, sbn.packageName, title, text)
    }
}
