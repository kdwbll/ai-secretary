package com.secondbrain.app

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class ChatExchange(val id: Long, val createdAt: String, val user: String, val assistant: String)
data class CollectedEvent(val id: Long, val createdAt: String, val source: String, val kind: String, val title: String, val content: String)
data class UploadReceipt(val name: String, val summary: String)
data class RemoteFile(val hash: String, val name: String, val createdAt: String, val summary: String)
data class TokenDay(val date: String, val tokens: Long, val cost: Double)
data class TokenActivity(val totalTokens: Long, val totalCost: Double, val days: List<TokenDay>)

object ApiClient {
    private val client = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    private fun base(server: String) = server.trim().trimEnd('/')

    suspend fun health(server: String): Boolean = withContext(Dispatchers.IO) {
        try {
            client.newCall(Request.Builder().url("${base(server)}/api/health").get().build()).execute().use { response -> response.isSuccessful }
        } catch (_: Exception) { false }
    }

    suspend fun chats(server: String): List<ChatExchange> = withContext(Dispatchers.IO) {
        client.newCall(Request.Builder().url("${base(server)}/api/chats?limit=100").get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取会话失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("chats")
            buildList {
                for (index in array.length() - 1 downTo 0) {
                    val item = array.getJSONObject(index)
                    add(ChatExchange(item.getLong("id"), item.optString("created_at"), item.optString("user_message"), item.optString("assistant_message")))
                }
            }
        }
    }

    suspend fun sendChat(server: String, message: String): String = withContext(Dispatchers.IO) {
        val body = JSONObject().put("message", message).toString().toRequestBody("application/json".toMediaTypeOrNull())
        client.newCall(Request.Builder().url("${base(server)}/api/chat").post(body).build()).execute().use { response ->
            if (!response.isSuccessful) error("发送失败（${response.code}）")
            JSONObject(response.body?.string().orEmpty()).optString("answer", "已发送")
        }
    }

    suspend fun events(server: String): List<CollectedEvent> = withContext(Dispatchers.IO) {
        client.newCall(Request.Builder().url("${base(server)}/api/events?limit=100").get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取采集记录失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("events")
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.getJSONObject(index)
                    val payload = item.optJSONObject("payload") ?: JSONObject()
                    add(CollectedEvent(item.getLong("id"), item.optString("created_at"), item.optString("source"), item.optString("kind"), payload.optString("title", item.optString("kind")), payload.optString("raw", payload.optString("summary", "暂无内容"))))
                }
            }
        }
    }

    suspend fun upload(context: Context, server: String, uri: Uri): UploadReceipt = withContext(Dispatchers.IO) {
        val name = displayName(context, uri)
        val mime = context.contentResolver.getType(uri) ?: "application/octet-stream"
        val body = ContentUriBody(context, uri, mime)
        val multipart = MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("file", name, body).build()
        client.newCall(Request.Builder().url("${base(server)}/api/upload").post(multipart).build()).execute().use { response ->
            if (!response.isSuccessful) error("上传失败（${response.code}）")
            val result = JSONObject(response.body?.string().orEmpty())
            UploadReceipt(name, result.optString("extracted_text", "文件已归档").take(500))
        }
    }

    suspend fun files(server: String): List<RemoteFile> = withContext(Dispatchers.IO) {
        client.newCall(Request.Builder().url("${base(server)}/api/files?limit=100").get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取文件记录失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("files")
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.getJSONObject(index)
                    add(RemoteFile(item.getString("hash"), item.optString("original_name"), item.optString("created_at"), item.optString("extracted_text")))
                }
            }
        }
    }

    suspend fun usage(server: String): TokenActivity = withContext(Dispatchers.IO) {
        client.newCall(Request.Builder().url("${base(server)}/api/usage/activity?days=365").get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取 Token 用量失败（${response.code}）")
            val result = JSONObject(response.body?.string().orEmpty())
            val totals = result.getJSONObject("totals")
            val array = result.getJSONArray("days")
            val days = buildList {
                for (index in 0 until array.length()) {
                    val item = array.getJSONObject(index)
                    add(TokenDay(item.getString("date"), item.optLong("total_tokens"), item.optDouble("estimated_cost")))
                }
            }
            TokenActivity(totals.optLong("prompt_tokens") + totals.optLong("completion_tokens"), totals.optDouble("estimated_cost"), days)
        }
    }

    suspend fun deleteFile(server: String, hash: String) = withContext(Dispatchers.IO) {
        client.newCall(Request.Builder().url("${base(server)}/api/files/$hash").delete().build()).execute().use { response ->
            if (!response.isSuccessful) error("删除文件失败（${response.code}）")
        }
    }

    private fun displayName(context: Context, uri: Uri): String {
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) return cursor.getString(0)
        }
        return uri.lastPathSegment ?: "mobile-upload"
    }
}

private class ContentUriBody(private val context: Context, private val uri: Uri, private val mime: String) : RequestBody() {
    override fun contentType() = mime.toMediaTypeOrNull()
    override fun contentLength(): Long = context.contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1
    override fun writeTo(sink: BufferedSink) {
        context.contentResolver.openInputStream(uri)?.use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                sink.write(buffer, 0, count)
            }
        } ?: error("无法读取所选文件")
    }
}
