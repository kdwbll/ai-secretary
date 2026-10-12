package com.secondbrain.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val preferences = context.getSharedPreferences("second_brain", Context.MODE_PRIVATE)
        val server = preferences.getString("server", null) ?: return
        val token = preferences.getString("access_token", null) ?: return
        Telephony.Sms.Intents.getMessagesFromIntent(intent).forEach { sms ->
            preferences.edit().putLong("sms_last_captured_at", System.currentTimeMillis()).apply()
            SyncWorker.enqueueSms(context, server, token, sms.originatingAddress ?: "", sms.messageBody)
        }
    }
}
