package com.secondbrain.app

import android.content.Context
import androidx.work.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

class SyncWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result = when (send(applicationContext, inputData)) {
        UploadResult.SUCCESS -> Result.success()
        UploadResult.UNAUTHORIZED -> Result.failure()
        UploadResult.RETRY -> Result.retry()
    }

    companion object {
        private enum class UploadResult { SUCCESS, UNAUTHORIZED, RETRY }

        private val client = OkHttpClient.Builder()
            .connectTimeout(6, TimeUnit.SECONDS)
            .readTimeout(12, TimeUnit.SECONDS)
            .build()

        private fun escape(value: String) = value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")

        private fun send(context: Context, data: Data): UploadResult {
            val server = data.getString("server") ?: return UploadResult.UNAUTHORIZED
            val token = data.getString("token") ?: return UploadResult.UNAUTHORIZED
            val kind = data.getString("kind") ?: "chat"
            val message = escape(data.getString("message") ?: return UploadResult.SUCCESS)
            val endpoint: String
            val json: String
            when (kind) {
                "sms" -> { endpoint = "/api/ingest/sms"; json = "{\"text\":\"$message\",\"sender\":\"${escape(data.getString("sender") ?: "")}\"}" }
                "notification" -> { endpoint = "/api/ingest/notification"; json = "{\"package\":\"${escape(data.getString("package") ?: "")}\",\"title\":\"${escape(data.getString("title") ?: "")}\",\"text\":\"$message\"}" }
                else -> { endpoint = "/api/chat"; json = "{\"message\":\"$message\"}" }
            }
            val body = json.toRequestBody("application/json".toMediaType())
            return try {
                client.newCall(Request.Builder().url("$server$endpoint").header("Authorization", "Bearer $token").post(body).build()).execute().use { response ->
                    when {
                        response.isSuccessful -> {
                            if (kind == "notification" || kind == "sms") {
                                val preferenceKey = if (kind == "notification") "notification_last_uploaded_at" else "sms_last_uploaded_at"
                                context.getSharedPreferences("second_brain", Context.MODE_PRIVATE).edit()
                                    .putLong(preferenceKey, System.currentTimeMillis()).apply()
                            }
                            UploadResult.SUCCESS
                        }
                        response.code == 401 -> UploadResult.UNAUTHORIZED
                        else -> UploadResult.RETRY
                    }
                }
            } catch (_: Exception) {
                UploadResult.RETRY
            }
        }

        private fun enqueue(context: Context, data: Data) {
            val request = OneTimeWorkRequestBuilder<SyncWorker>().setInputData(data)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
                .build()
            WorkManager.getInstance(context).enqueue(request)
        }

        /** Send while the listener/receiver is alive; queue only when it fails. */
        private fun sendOrEnqueue(context: Context, data: Data) {
            if (send(context, data) == UploadResult.RETRY) enqueue(context, data)
        }

        private fun submitNow(context: Context, data: Data) {
            Thread { sendOrEnqueue(context.applicationContext, data) }.start()
        }

        fun enqueueChat(context: Context, server: String, token: String, message: String) = enqueue(context, workDataOf("kind" to "chat", "server" to server, "token" to token, "message" to message))
        fun sendSmsNow(context: Context, server: String, token: String, sender: String, message: String) = sendOrEnqueue(context, workDataOf("kind" to "sms", "server" to server, "token" to token, "sender" to sender, "message" to message))
        fun enqueueSms(context: Context, server: String, token: String, sender: String, message: String) = submitNow(context, workDataOf("kind" to "sms", "server" to server, "token" to token, "sender" to sender, "message" to message))
        fun enqueueNotification(context: Context, server: String, token: String, packageName: String, title: String, text: String) = submitNow(context, workDataOf("kind" to "notification", "server" to server, "token" to token, "package" to packageName, "title" to title, "message" to text))
    }
}
