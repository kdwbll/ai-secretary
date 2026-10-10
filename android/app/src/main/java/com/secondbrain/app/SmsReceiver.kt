package com.secondbrain.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val server = context.getSharedPreferences("second_brain", Context.MODE_PRIVATE).getString("server", null) ?: return
        Telephony.Sms.Intents.getMessagesFromIntent(intent).forEach { sms ->
            SyncWorker.enqueueSms(context, server, sms.originatingAddress ?: "", sms.messageBody)
        }
    }
}
