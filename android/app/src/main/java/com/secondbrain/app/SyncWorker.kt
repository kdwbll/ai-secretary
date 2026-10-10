package com.secondbrain.app

import android.content.Context
import androidx.work.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

class SyncWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val server = inputData.getString("server") ?: return Result.failure()
        val message = inputData.getString("message") ?: return Result.success()
        val escaped = message.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")
        val body = "{\"message\":\"$escaped\"}".toRequestBody("application/json".toMediaType())
        val response = OkHttpClient().newCall(Request.Builder().url("$server/api/chat").post(body).build()).execute()
        return if (response.isSuccessful) Result.success() else Result.retry()
    }

    companion object {
        fun enqueue(context: Context, server: String, message: String) {
            // WorkManager is intentionally used so content survives temporary disconnection.
            val request = OneTimeWorkRequestBuilder<SyncWorker>().setInputData(workDataOf("server" to server, "message" to message)).setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
            WorkManager.getInstance(context).enqueue(request)
        }
    }
}
