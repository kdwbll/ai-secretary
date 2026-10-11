package com.secondbrain.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
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
        val notification = android.app.Notification.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(item.title)
            .setContentText(item.body)
            .setStyle(android.app.Notification.BigTextStyle().bigText(item.body))
            .setAutoCancel(true)
            .build()
        manager.notify(item.id.toInt(), notification)
    }
}
