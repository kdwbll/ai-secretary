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
            OkHttpClient().newCall(Request.Builder().url("$server$endpoint").post(body).build()).execute().use { response ->
                if (response.isSuccessful) Result.success() else Result.retry()
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

        fun enqueueChat(context: Context, server: String, message: String) = enqueue(context, workDataOf("kind" to "chat", "server" to server, "message" to message))
        fun enqueueSms(context: Context, server: String, sender: String, message: String) = enqueue(context, workDataOf("kind" to "sms", "server" to server, "sender" to sender, "message" to message))
        fun enqueueNotification(context: Context, server: String, packageName: String, title: String, text: String) = enqueue(context, workDataOf("kind" to "notification", "server" to server, "package" to packageName, "title" to title, "message" to text))
    }
}
