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
        val token = inputData.getString("token") ?: return Result.failure()
        val kind = inputData.getString("kind") ?: "chat"
        val message = escape(inputData.getString("message") ?: return Result.success())
        val endpoint: String
        val json: String
        when (kind) {
            "sms" -> { endpoint = "/api/ingest/sms"; json = "{\"text\":\"$message\",\"sender\":\"${escape(inputData.getString("sender") ?: "")}\"}" }
            "notification" -> { endpoint = "/api/ingest/notification"; json = "{\"package\":\"${escape(inputData.getString("package") ?: "")}\",\"title\":\"${escape(inputData.getString("title") ?: "")}\",\"text\":\"$message\"}" }
            else -> { endpoint = "/api/chat"; json = "{\"message\":\"$message\"}" }
        }
        val body = json.toRequestBody("application/json".toMediaType())
        return try {
            OkHttpClient().newCall(Request.Builder().url("$server$endpoint").header("Authorization", "Bearer $token").post(body).build()).execute().use { response ->
                val result = if (response.isSuccessful) Result.success() else if (response.code == 401) Result.failure() else Result.retry()
                if (kind == "notification" && response.isSuccessful) {
                    applicationContext.getSharedPreferences("second_brain", Context.MODE_PRIVATE).edit()
                        .putLong("notification_last_uploaded_at", System.currentTimeMillis()).apply()
                }
                result
            }
        } catch (_: Exception) {
            Result.retry()
        }
    }

    companion object {
        private fun escape(value: String) = value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")

        private fun enqueue(context: Context, data: Data) {
            // WorkManager is intentionally used so content survives temporary disconnection.
            val request = OneTimeWorkRequestBuilder<SyncWorker>().setInputData(data).setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
            WorkManager.getInstance(context).enqueue(request)
        }

        fun enqueueChat(context: Context, server: String, token: String, message: String) = enqueue(context, workDataOf("kind" to "chat", "server" to server, "token" to token, "message" to message))
        fun enqueueSms(context: Context, server: String, token: String, sender: String, message: String) = enqueue(context, workDataOf("kind" to "sms", "server" to server, "token" to token, "sender" to sender, "message" to message))
        fun enqueueNotification(context: Context, server: String, token: String, packageName: String, title: String, text: String) = enqueue(context, workDataOf("kind" to "notification", "server" to server, "token" to token, "package" to packageName, "title" to title, "message" to text))
    }
}
