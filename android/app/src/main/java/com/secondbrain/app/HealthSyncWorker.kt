package com.secondbrain.app

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

class HealthSyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val preferences = applicationContext.getSharedPreferences("second_brain", Context.MODE_PRIVATE)
        val server = preferences.getString("server", "").orEmpty().trimEnd('/')
        val token = preferences.getString("access_token", "").orEmpty()
        if (server.isBlank() || token.isBlank()) return Result.success()
        return try {
            if (!HealthConnectReader.hasReadPermissions(applicationContext) || !HealthConnectReader.canReadInBackground(applicationContext)) return Result.success()
            val samples = HealthConnectReader.recent(applicationContext)
            ApiClient.syncHealth(server, token, samples)
            preferences.edit().putLong("health_last_uploaded_at", System.currentTimeMillis()).apply()
            Result.success()
        } catch (_: SecurityException) {
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }

    companion object {
        private const val WORK_NAME = "second-brain-health-sync"

        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<HealthSyncWorker>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME, ExistingPeriodicWorkPolicy.UPDATE, request,
            )
        }
    }
}
