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
        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent).map { sms ->
            (sms.originatingAddress ?: "") to sms.messageBody
        }
        val pendingResult = goAsync()
        Thread {
            try {
                messages.forEach { (sender, message) ->
                    preferences.edit().putLong("sms_last_captured_at", System.currentTimeMillis()).apply()
                    SyncWorker.sendSmsNow(context.applicationContext, server, token, sender, message)
                }
            } finally {
                pendingResult.finish()
            }
        }.start()
    }
}
