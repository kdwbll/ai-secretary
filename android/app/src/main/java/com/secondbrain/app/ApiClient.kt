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
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit

data class MapSpec(
    val query: String,
    val mode: String,
    val label: String,
    val latitude: Double?,
    val longitude: Double?,
)
data class MapConfig(val apiKey: String, val securityCode: String)
data class GuidedQuestion(val question: String, val options: List<String>)
data class MemoryCandidate(val id: Long, val fact: String, val reason: String)
data class ChatExchange(
    val id: Long,
    val createdAt: String,
    val user: String,
    val assistant: String,
    val maps: List<MapSpec>,
    val guidance: GuidedQuestion?,
    val memoryFailed: Boolean = false,
    val memoryCandidates: List<MemoryCandidate> = emptyList(),
)
data class CollectedEvent(val id: Long, val createdAt: String, val source: String, val kind: String, val title: String, val content: String)
data class UploadReceipt(val name: String, val summary: String)
data class RemoteFile(val hash: String, val name: String, val createdAt: String, val summary: String)
data class TokenDay(val date: String, val tokens: Long, val cost: Double)
data class TokenActivity(val totalTokens: Long, val totalCost: Double, val days: List<TokenDay>)
data class RemoteNotification(val id: Long, val kind: String, val title: String, val body: String)
data class RemoteTask(val id: Long, val title: String, val status: String, val dueAt: String?, val schedule: String, val nextRunAt: String?, val enabled: Boolean)
data class RemoteGoal(val id: Long, val title: String, val description: String, val status: String, val dueAt: String?, val completedTasks: Int, val taskCount: Int, val tasks: List<RemoteTask>)
data class TaskActivity(val id: Long, val taskId: Long, val taskTitle: String, val goalTitle: String, val status: String, val trigger: String, val startedAt: String, val nextRunAt: String?, val error: String)
data class RemoteApproval(
    val id: Long, val actionType: String, val level: String, val connector: String,
    val summary: String, val target: String, val payload: String, val status: String, val expiresAt: String,
)
data class ConnectorPermission(
    val connector: String, val displayName: String, val scopes: List<String>,
    val mode: String, val enabled: Boolean, val lastUsedAt: String,
)
data class LocalCalendarEvent(val id: Long, val title: String, val startAt: String, val endAt: String, val location: String)
data class LocalEmailDraft(val id: Long, val recipients: List<String>, val subject: String, val body: String, val updatedAt: String)
data class RemoteArtifact(val id: Long, val kind: String, val title: String, val preview: String, val version: Int, val source: String, val updatedAt: String)

object ApiClient {
    private val client = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    private fun base(server: String) = server.trim().trimEnd('/')

    private fun request(server: String, path: String, token: String = ""): Request.Builder =
        Request.Builder().url("${base(server)}$path").apply {
            if (token.isNotBlank()) header("Authorization", "Bearer $token")
        }

    suspend fun health(server: String, token: String): Boolean = withContext(Dispatchers.IO) {
        try {
            client.newCall(request(server, "/api/auth/status", token).get().build()).execute().use { response ->
                response.isSuccessful && JSONObject(response.body?.string().orEmpty()).optBoolean("authenticated")
            }
        } catch (_: Exception) { false }
    }

    suspend fun pair(server: String, code: String, deviceName: String): String = withContext(Dispatchers.IO) {
        val body = JSONObject().put("code", code).put("device_name", deviceName).toString().toRequestBody("application/json".toMediaTypeOrNull())
        client.newCall(request(server, "/api/auth/pair").post(body).build()).execute().use { response ->
            val content = response.body?.string().orEmpty()
            if (!response.isSuccessful) error(runCatching { JSONObject(content).optString("detail") }.getOrNull().orEmpty().ifBlank { "配对失败（${response.code}）" })
            JSONObject(content).getString("token")
        }
    }

    suspend fun chats(server: String, token: String): List<ChatExchange> = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/chats?limit=100", token).get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取会话失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("chats")
            buildList {
                for (index in array.length() - 1 downTo 0) {
                    val item = array.getJSONObject(index)
                    val mapArray = item.optJSONObject("attachments")?.optJSONArray("maps")
                    val maps = buildList {
                        if (mapArray != null) for (mapIndex in 0 until mapArray.length()) {
                            val map = mapArray.getJSONObject(mapIndex)
                            add(MapSpec(
                                query = map.optString("query"),
                                mode = map.optString("mode", "place"),
                                label = map.optString("label"),
                                latitude = map.optionalDouble("latitude"),
                                longitude = map.optionalDouble("longitude"),
                            ))
                        }
                    }
                    val guidanceObject = item.optJSONObject("attachments")?.optJSONObject("guidance")
                    val guidance = guidanceObject?.let { guide ->
                        val options = guide.optJSONArray("options")?.let { values ->
                            buildList { for (optionIndex in 0 until values.length()) add(values.optString(optionIndex)) }
                        }.orEmpty().filter { it.isNotBlank() }
                        GuidedQuestion(guide.optString("question"), options).takeIf { it.question.isNotBlank() && it.options.isNotEmpty() }
                    }
                    val candidates = item.optJSONObject("attachments")?.optJSONArray("memory_candidates")?.let { values ->
                        buildList { for (index in 0 until values.length()) {
                            val candidate = values.getJSONObject(index)
                            add(MemoryCandidate(candidate.getLong("id"), candidate.optString("fact"), candidate.optString("reason")))
                        } }
                    }.orEmpty()
                    add(ChatExchange(item.getLong("id"), item.optString("created_at"), item.optString("user_message"), item.optString("assistant_message"), maps, guidance, item.optJSONObject("attachments")?.optString("memory_status") == "failed", candidates))
                }
            }
        }
    }

    suspend fun mapConfig(server: String, token: String): MapConfig = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/map/config", token).get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取地图配置失败（${response.code}）")
            val result = JSONObject(response.body?.string().orEmpty())
            MapConfig(result.optString("api_key"), result.optString("security_code"))
        }
    }

    suspend fun resolveMemory(server: String, token: String, candidateId: Long, accept: Boolean) = withContext(Dispatchers.IO) {
        val body = JSONObject().put("accept", accept).toString().toRequestBody("application/json".toMediaTypeOrNull())
        client.newCall(request(server, "/api/memory-candidates/$candidateId/resolve", token).post(body).build()).execute().use { response ->
            if (!response.isSuccessful) error("处理待确认记忆失败（${response.code}）")
        }
    }

    suspend fun retryMemory(server: String, token: String, chatId: Long): Boolean = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/chats/$chatId/retry-memory", token).post("{}".toRequestBody("application/json".toMediaTypeOrNull())).build()).execute().use { response ->
            if (!response.isSuccessful) error("记忆重试失败（${response.code}）")
            JSONObject(response.body?.string().orEmpty()).optBoolean("saved")
        }
    }

    suspend fun sendChat(server: String, token: String, message: String): String = withContext(Dispatchers.IO) {
        val body = JSONObject().put("message", message).toString().toRequestBody("application/json".toMediaTypeOrNull())
        client.newCall(request(server, "/api/chat", token).post(body).build()).execute().use { response ->
            if (!response.isSuccessful) error("发送失败（${response.code}）")
            JSONObject(response.body?.string().orEmpty()).optString("answer", "已发送")
        }
    }

    suspend fun reportLocation(server: String, token: String, latitude: Double, longitude: Double) = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("source", "android").put("latitude", latitude).put("longitude", longitude)
            .put("label", "Android 伴侣主动上报").put("enabled", true)
            .toString().toRequestBody("application/json".toMediaTypeOrNull())
        client.newCall(request(server, "/api/location/report", token).post(body).build()).execute().use { response ->
            if (!response.isSuccessful) error("位置上报失败（${response.code}）")
        }
    }

    suspend fun syncCalendar(server: String, token: String, windowStart: String, windowEnd: String, events: List<CalendarEvent>) = withContext(Dispatchers.IO) {
        val body = JSONObject().put("window_start", windowStart).put("window_end", windowEnd)
        val records = org.json.JSONArray()
        events.forEach { event ->
            records.put(JSONObject()
                .put("external_id", event.externalId).put("title", event.title)
                .put("start_at", event.startAt).put("end_at", event.endAt).put("all_day", event.allDay)
                .put("location", event.location).put("description", event.description).put("calendar_name", event.calendarName))
        }
        body.put("events", records)
        client.newCall(request(server, "/api/ingest/calendar", token)
            .post(body.toString().toRequestBody("application/json".toMediaTypeOrNull())).build()).execute().use { response ->
            if (!response.isSuccessful) error("日程同步失败（${response.code}）")
        }
    }

    suspend fun notifications(server: String, token: String, afterId: Long): List<RemoteNotification> = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/notifications?after_id=$afterId", token).get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取提醒失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("notifications")
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.getJSONObject(index)
                    add(RemoteNotification(item.getLong("id"), item.optString("kind"), item.optString("title"), item.optString("body")))
                }
            }
        }
    }

    suspend fun events(server: String, token: String): List<CollectedEvent> = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/events?limit=100", token).get().build()).execute().use { response ->
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

    suspend fun goals(server: String, token: String): List<RemoteGoal> = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/goals?include_closed=true", token).get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取目标失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("goals")
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.getJSONObject(index)
                    val tasks = item.optJSONArray("tasks")?.let { values -> buildList {
                        for (taskIndex in 0 until values.length()) {
                            val task = values.getJSONObject(taskIndex)
                            add(RemoteTask(task.getLong("id"), task.optString("title"), task.optString("status", "pending"), task.optString("due_at").takeIf { it.isNotBlank() }, task.optString("schedule", "manual"), task.optString("next_run_at").takeIf { it.isNotBlank() }, task.optBoolean("enabled", true)))
                        }
                    } }.orEmpty()
                    add(RemoteGoal(item.getLong("id"), item.optString("title"), item.optString("description"), item.optString("status", "active"), item.optString("due_at").takeIf { it.isNotBlank() }, item.optInt("completed_task_count"), item.optInt("task_count"), tasks))
                }
            }
        }
    }

    suspend fun createGoal(server: String, token: String, title: String): RemoteGoal = withContext(Dispatchers.IO) {
        val body = JSONObject().put("title", title).toString().toRequestBody("application/json".toMediaTypeOrNull())
        client.newCall(request(server, "/api/goals", token).header("X-Idempotency-Key", "android-${java.util.UUID.randomUUID()}").post(body).build()).execute().use { response ->
            if (!response.isSuccessful) error("创建目标失败（${response.code}）")
            val item = JSONObject(response.body?.string().orEmpty())
            RemoteGoal(item.getLong("id"), item.optString("title"), item.optString("description"), item.optString("status"), item.optString("due_at").takeIf { it.isNotBlank() }, 0, 0, emptyList())
        }
    }

    suspend fun setGoalStatus(server: String, token: String, goalId: Long, status: String) = withContext(Dispatchers.IO) {
        val body = JSONObject().put("status", status).toString().toRequestBody("application/json".toMediaTypeOrNull())
        client.newCall(request(server, "/api/goals/$goalId/status", token).post(body).build()).execute().use { response ->
            if (!response.isSuccessful) error("更新目标失败（${response.code}）")
        }
    }

    suspend fun setTaskStatus(server: String, token: String, taskId: Long, status: String) = withContext(Dispatchers.IO) {
        val body = JSONObject().put("status", status).toString().toRequestBody("application/json".toMediaTypeOrNull())
        client.newCall(request(server, "/api/tasks/$taskId/status", token).post(body).build()).execute().use { response ->
            if (!response.isSuccessful) error("更新任务失败（${response.code}）")
        }
    }

    suspend fun setTaskEnabled(server: String, token: String, taskId: Long, enabled: Boolean) = withContext(Dispatchers.IO) {
        val body = JSONObject().put("enabled", enabled).toString().toRequestBody("application/json".toMediaTypeOrNull())
        client.newCall(request(server, "/api/tasks/$taskId", token).put(body).build()).execute().use { response ->
            if (!response.isSuccessful) error("更新后台任务失败（${response.code}）")
        }
    }

    suspend fun activity(server: String, token: String): List<TaskActivity> = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/activity?limit=100", token).get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取活动记录失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("activity")
            buildList { for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                add(TaskActivity(item.getLong("id"), item.getLong("task_id"), item.optString("task_title"), item.optString("goal_title"), item.optString("status"), item.optString("trigger"), item.optString("started_at"), item.optString("next_run_at").takeIf { it.isNotBlank() }, item.optString("error")))
            } }
        }
    }

    suspend fun localCalendar(server: String, token: String): List<LocalCalendarEvent> = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/calendar/local", token).get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取本机日程失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("events")
            buildList { for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                add(LocalCalendarEvent(item.getLong("id"), item.optString("title"), item.optString("start_at"), item.optString("end_at"), item.optString("location")))
            } }
        }
    }

    suspend fun emailDrafts(server: String, token: String): List<LocalEmailDraft> = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/email/drafts", token).get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取邮件草稿失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("drafts")
            buildList { for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                val recipients = item.optJSONArray("recipients")?.let { values -> buildList {
                    for (recipientIndex in 0 until values.length()) add(values.optString(recipientIndex))
                } }.orEmpty()
                add(LocalEmailDraft(item.getLong("id"), recipients, item.optString("subject"), item.optString("body"), item.optString("updated_at")))
            } }
        }
    }

    suspend fun artifacts(server: String, token: String): List<RemoteArtifact> = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/artifacts", token).get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取 Artifact 失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("artifacts")
            buildList { for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                add(RemoteArtifact(item.getLong("id"), item.optString("kind"), item.optString("title"), item.optString("preview"), item.optInt("current_version", 1), item.optString("source"), item.optString("updated_at")))
            } }
        }
    }

    suspend fun executeCalendarApproval(server: String, token: String, approvalId: Long) = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/calendar/suggestions/$approvalId/execute", token)
            .post("{}".toRequestBody("application/json".toMediaTypeOrNull())).build()).execute().use { response ->
            val content = response.body?.string().orEmpty()
            if (!response.isSuccessful) error(runCatching { JSONObject(content).optString("detail") }.getOrNull().orEmpty().ifBlank { "创建本机日程失败（${response.code}）" })
        }
    }

    suspend fun approvals(server: String, token: String): List<RemoteApproval> = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/approvals?limit=100", token).get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取审批失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("approvals")
            buildList { for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                add(RemoteApproval(
                    item.getLong("id"), item.optString("action_type"), item.optString("level"), item.optString("connector"),
                    item.optString("summary"), item.optString("target"), item.optJSONObject("exact_payload")?.toString(2) ?: "{}",
                    item.optString("status"), item.optString("expires_at"),
                ))
            } }
        }
    }

    suspend fun decideApproval(server: String, token: String, approvalId: Long, decision: String, editedPayload: String? = null) = withContext(Dispatchers.IO) {
        val body = JSONObject().put("decision", decision)
        if (editedPayload != null) body.put("edited_payload", JSONObject(editedPayload))
        client.newCall(request(server, "/api/approvals/$approvalId/decision", token)
            .post(body.toString().toRequestBody("application/json".toMediaTypeOrNull())).build()).execute().use { response ->
            val content = response.body?.string().orEmpty()
            if (!response.isSuccessful) error(runCatching { JSONObject(content).optString("detail") }.getOrNull().orEmpty().ifBlank { "处理审批失败（${response.code}）" })
        }
    }

    suspend fun executeForget(server: String, token: String, approvalId: Long) = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/forget/$approvalId/execute", token)
            .post("{}".toRequestBody("application/json".toMediaTypeOrNull())).build()).execute().use { response ->
            if (!response.isSuccessful) error("执行遗忘失败（${response.code}）")
        }
    }

    suspend fun connectorPermissions(server: String, token: String): List<ConnectorPermission> = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/connectors/permissions", token).get().build()).execute().use { response ->
            if (!response.isSuccessful) error("读取连接器权限失败（${response.code}）")
            val array = JSONObject(response.body?.string().orEmpty()).getJSONArray("connectors")
            buildList { for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                val scopes = item.optJSONArray("scopes")?.let { values -> buildList {
                    for (scopeIndex in 0 until values.length()) add(values.optString(scopeIndex))
                } }.orEmpty()
                add(ConnectorPermission(item.optString("connector"), item.optString("display_name"), scopes,
                    item.optString("mode", "read"), item.optBoolean("enabled"), item.optString("last_used_at")))
            } }
        }
    }

    suspend fun setConnectorPermission(server: String, token: String, connector: String, enabled: Boolean) = withContext(Dispatchers.IO) {
        val body = JSONObject().put("enabled", enabled).toString().toRequestBody("application/json".toMediaTypeOrNull())
        client.newCall(request(server, "/api/connectors/permissions/${URLEncoder.encode(connector, StandardCharsets.UTF_8.name())}", token).put(body).build()).execute().use { response ->
            if (!response.isSuccessful) error("更新连接器权限失败（${response.code}）")
        }
    }

    suspend fun upload(context: Context, server: String, token: String, uri: Uri): UploadReceipt = withContext(Dispatchers.IO) {
        val name = displayName(context, uri)
        val mime = context.contentResolver.getType(uri) ?: "application/octet-stream"
        val body = ContentUriBody(context, uri, mime)
        val multipart = MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("file", name, body).build()
        client.newCall(request(server, "/api/upload", token).post(multipart).build()).execute().use { response ->
            if (!response.isSuccessful) error("上传失败（${response.code}）")
            val result = JSONObject(response.body?.string().orEmpty())
            UploadReceipt(name, result.optString("extracted_text", "文件已归档").take(500))
        }
    }

    suspend fun files(server: String, token: String): List<RemoteFile> = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/files?limit=100", token).get().build()).execute().use { response ->
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

    suspend fun usage(server: String, token: String): TokenActivity = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/usage/activity?days=365", token).get().build()).execute().use { response ->
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

    suspend fun deleteFile(server: String, token: String, hash: String) = withContext(Dispatchers.IO) {
        client.newCall(request(server, "/api/files/$hash", token).delete().build()).execute().use { response ->
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

private fun JSONObject.optionalDouble(name: String): Double? =
    if (has(name) && !isNull(name)) optDouble(name).takeUnless { it.isNaN() } else null

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
