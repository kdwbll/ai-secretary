package com.secondbrain.app

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

class SecondBrainNotificationListener : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val extras = sbn.notification.extras
        val title = extras.getCharSequence("android.title")?.toString() ?: ""
        val text = extras.getCharSequence("android.text")?.toString() ?: return
        // Production pairing stores the selected LAN endpoint; this MVP leaves collection opt-in until configured.
        val server = getSharedPreferences("second_brain", MODE_PRIVATE).getString("server", null) ?: return
        val json = "{\"package\":\"${sbn.packageName}\",\"title\":\"${title.replace("\"", "\\\"")}\",\"text\":\"${text.replace("\"", "\\\"")}\"}"
        Thread { runCatching { OkHttpClient().newCall(Request.Builder().url("$server/api/ingest/notification").post(json.toRequestBody("application/json".toMediaType())).build()).execute().close() } }.start()
    }
}
