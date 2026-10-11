package com.secondbrain.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build

object AndroidNotifications {
    private const val CHANNEL_ID = "second_brain_reminders"

    fun show(context: Context, item: RemoteNotification) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "第二大脑提醒", NotificationManager.IMPORTANCE_DEFAULT)
            )
        }
        val openIntent = Intent(context, MainActivity::class.java).apply {
            action = "com.secondbrain.app.OPEN_NOTIFICATION.${item.id}"
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
            putExtra(EXTRA_NOTIFICATION_ID, item.id)
            putExtra(EXTRA_NOTIFICATION_KIND, item.kind)
            putExtra(EXTRA_NOTIFICATION_TITLE, item.title)
            putExtra(EXTRA_NOTIFICATION_BODY, item.body)
        }
        val contentIntent = PendingIntent.getActivity(
            context,
            item.id.toInt(),
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val preview = item.body.replace(Regex("[#*_`]+"), "").replace(Regex("\\s+"), " ").trim()
        val notification = android.app.Notification.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(item.title)
            .setContentText(preview)
            .setStyle(android.app.Notification.BigTextStyle().bigText(preview))
            .setContentIntent(contentIntent)
            .setAutoCancel(true)
            .build()
        manager.notify(item.id.toInt(), notification)
    }

    const val EXTRA_NOTIFICATION_ID = "notification_id"
    const val EXTRA_NOTIFICATION_KIND = "notification_kind"
    const val EXTRA_NOTIFICATION_TITLE = "notification_title"
    const val EXTRA_NOTIFICATION_BODY = "notification_body"
}
