package com.secondbrain.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val server = context.getSharedPreferences("second_brain", Context.MODE_PRIVATE).getString("server", null) ?: return
        val pending = goAsync()
        Thread {
            try {
                Telephony.Sms.Intents.getMessagesFromIntent(intent).forEach { sms ->
                    val text = sms.messageBody.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")
                    val sender = (sms.originatingAddress ?: "").replace("\"", "\\\"")
                    val json = "{\"text\":\"$text\",\"sender\":\"$sender\"}"
                    runCatching { OkHttpClient().newCall(Request.Builder().url("$server/api/ingest/sms").post(json.toRequestBody("application/json".toMediaType())).build()).execute().close() }
                }
            } finally { pending.finish() }
        }.start()
    }
}
