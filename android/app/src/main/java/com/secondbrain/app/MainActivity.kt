package com.secondbrain.app

import android.Manifest
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.Html
import android.text.method.LinkMovementMethod
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.JavascriptInterface
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.NotificationManagerCompat
import androidx.compose.foundation.background
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.time.temporal.ChronoUnit

class MainActivity : ComponentActivity() {
    private val requestPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { }
    private var currentIntent by mutableStateOf<Intent?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        currentIntent = intent
        val permissions = mutableListOf(Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS)
        if (Build.VERSION.SDK_INT >= 33) permissions += Manifest.permission.POST_NOTIFICATIONS
        requestPermissions.launch(permissions.toTypedArray())
        setContent { SecondBrainApp(currentIntent) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        currentIntent = intent
    }
}

private val Forest = Color(0xFF315D49)
private val Paper = Color(0xFFF5F1E8)

private fun notificationListenerStatus(context: Context): String {
    val preferences = context.getSharedPreferences("second_brain", Context.MODE_PRIVATE)
    if (!NotificationManagerCompat.getEnabledListenerPackages(context).contains(context.packageName)) {
        return "系统尚未授予通知读取权限。请在系统通知使用权中关闭后重新开启“第二大脑”。"
    }
    fun at(key: String): String {
        val millis = preferences.getLong(key, 0)
        return if (millis == 0L) "暂无" else java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT, java.text.DateFormat.MEDIUM).format(java.util.Date(millis))
    }
    return "通知监听已授权 · 最近捕获：${at("notification_last_captured_at")} · 最近上传：${at("notification_last_uploaded_at")}"
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun SecondBrainApp(intent: Intent?) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val preferences = remember { context.getSharedPreferences("second_brain", Context.MODE_PRIVATE) }
    var server by remember { mutableStateOf(preferences.getString("server", "http://192.168.1.2:8765") ?: "http://192.168.1.2:8765") }
    var token by remember { mutableStateOf(preferences.getString("access_token", "") ?: "") }
    var pairingCode by remember { mutableStateOf("") }
    var draft by remember { mutableStateOf(intent?.getStringExtra(Intent.EXTRA_TEXT) ?: "") }
    var selectedTab by remember { mutableIntStateOf(0) }
    var connected by remember { mutableStateOf<Boolean?>(null) }
    var chats by remember { mutableStateOf<List<ChatExchange>>(emptyList()) }
    var events by remember { mutableStateOf<List<CollectedEvent>>(emptyList()) }
    var files by remember { mutableStateOf<List<RemoteFile>>(emptyList()) }
    var usage by remember { mutableStateOf<TokenActivity?>(null) }
    var mapConfig by remember { mutableStateOf<MapConfig?>(null) }
    var notice by remember { mutableStateOf("正在检查电脑连接…") }
    var sending by remember { mutableStateOf(false) }
    var uploading by remember { mutableStateOf(false) }
    var deleteTarget by remember { mutableStateOf<RemoteFile?>(null) }
    var openedNotification by remember { mutableStateOf<RemoteNotification?>(null) }
    var notificationStatus by remember { mutableStateOf(notificationListenerStatus(context)) }
    val scope = rememberCoroutineScope()
    val locationPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
        if (grants.values.any { it }) scope.launch {
            notice = "正在获取一次当前位置…"
            val location = runCatching { LocationReporter.current(context) }.getOrNull()
            if (location == null) notice = "没有获取到位置，请打开手机定位后重试"
            else runCatching { ApiClient.reportLocation(server, token, location.latitude, location.longitude) }
                .onSuccess { notice = "位置已安全上报；只会用于位置相关问题" }
                .onFailure { notice = "位置上报失败：${it.message}" }
        } else notice = "未授予位置权限，没有读取位置"
    }
    suspend fun refresh() {
        notificationStatus = notificationListenerStatus(context)
        connected = ApiClient.health(server, token)
        if (connected == true) {
            notice = "已安全联通电脑 · 数据自动同步"
            runCatching { ApiClient.chats(server, token) }.onSuccess { updated ->
                chats = updated
                // Do not cache an empty key forever: it is common to save the
                // AMap key on the computer after the phone first connects.
                if (updated.any { it.maps.isNotEmpty() }) {
                    runCatching { ApiClient.mapConfig(server, token) }.onSuccess { mapConfig = it }
                }
            }
            runCatching { events = ApiClient.events(server, token) }
            runCatching { files = ApiClient.files(server, token) }
            runCatching { usage = ApiClient.usage(server, token) }
            runCatching {
                val lastId = preferences.getLong("last_notification_id", 0)
                val incoming = ApiClient.notifications(server, token, lastId)
                if (lastId > 0) incoming.forEach { AndroidNotifications.show(context, it) }
                incoming.maxOfOrNull { it.id }?.let { preferences.edit().putLong("last_notification_id", it).apply() }
            }
        } else notice = if (token.isBlank()) "尚未配对 · 请在电脑设置页生成配对码" else "未连接或授权已撤销 · 请检查地址后重新配对"
    }

    fun syncCalendar() {
        scope.launch {
            if (token.isBlank() || connected != true) {
                notice = "请先连接电脑后再同步日程"
                return@launch
            }
            notice = "正在只读获取并同步近期日程…"
            val now = Instant.now()
            val from = now.minus(1, ChronoUnit.DAYS)
            val until = now.plus(14, ChronoUnit.DAYS)
            runCatching {
                val calendarEvents = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                    CalendarReader.recent(context, from.toEpochMilli(), until.toEpochMilli())
                }
                ApiClient.syncCalendar(server, token, from.toString(), until.toString(), calendarEvents)
                calendarEvents.size
            }.onSuccess { count ->
                notice = "已只读同步 $count 条近期日程到电脑"
                refresh()
            }.onFailure { notice = "日程同步失败：${it.message}" }
        }
    }
    val calendarPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) syncCalendar() else notice = "未授予日历读取权限，未读取任何日程"
    }

    LaunchedEffect(server, token) {
        while (isActive) {
            refresh()
            delay(2500)
        }
    }

    LaunchedEffect(intent) {
        val notificationId = intent?.getLongExtra(AndroidNotifications.EXTRA_NOTIFICATION_ID, -1L) ?: -1L
        if (notificationId >= 0) {
            openedNotification = RemoteNotification(
                notificationId,
                intent?.getStringExtra(AndroidNotifications.EXTRA_NOTIFICATION_KIND).orEmpty(),
                intent?.getStringExtra(AndroidNotifications.EXTRA_NOTIFICATION_TITLE).orEmpty().ifBlank { "第二大脑提醒" },
                intent?.getStringExtra(AndroidNotifications.EXTRA_NOTIFICATION_BODY).orEmpty(),
            )
        }
    }

    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) scope.launch {
            uploading = true
            notice = "正在上传 ${uris.size} 个文件…"
            var success = 0
            for (uri in uris) {
                runCatching { ApiClient.upload(context, server, token, uri) }
                    .onSuccess { success++ }
                    .onFailure { notice = "上传失败：${it.message}" }
            }
            uploading = false
            if (success > 0) {
                notice = "已上传 $success 个文件，电脑端也会显示"
                files = ApiClient.files(server, token)
                selectedTab = 2
            }
        }
    }

    if (deleteTarget != null) {
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("删除文件？") },
            text = { Text("将删除“${deleteTarget?.name}”的上传记录和电脑中的归档原件，此操作无法撤销。") },
            confirmButton = { TextButton(onClick = {
                val target = deleteTarget ?: return@TextButton
                deleteTarget = null
                scope.launch {
                    runCatching { ApiClient.deleteFile(server, token, target.hash) }
                        .onSuccess { files = ApiClient.files(server, token); notice = "文件已删除" }
                        .onFailure { notice = "删除失败：${it.message}" }
                }
            }) { Text("确认删除", color = Color(0xFFA04339)) } },
            dismissButton = { TextButton(onClick = { deleteTarget = null }) { Text("取消") } }
        )
    }


    openedNotification?.let { item ->
        AlertDialog(
            onDismissRequest = { openedNotification = null },
            title = { Text(item.title) },
            text = {
                Column(Modifier.fillMaxWidth().heightIn(max = 520.dp).verticalScroll(rememberScrollState())) {
                    Text(
                        when (item.kind) {
                            "morning" -> "今日早报"
                            "evening" -> "晚间复盘"
                            "weekly" -> "每周整理"
                            else -> "第二大脑通知"
                        },
                        style = MaterialTheme.typography.labelMedium,
                        color = Forest,
                    )
                    Spacer(Modifier.height(10.dp))
                    MarkdownText(item.body.ifBlank { "这条通知没有正文。" })
                }
            },
            confirmButton = { TextButton(onClick = { openedNotification = null }) { Text("知道了") } },
        )
    }

    MaterialTheme(colorScheme = lightColorScheme(primary = Forest, background = Paper, surface = Color(0xFFFFFDF8))) {
        Scaffold(
            topBar = {
                TopAppBar(title = { Text("第二大脑") }, actions = {
                    Surface(color = if (connected == true) Color(0xFFDDEBE2) else Color(0xFFF3DEDA), shape = RoundedCornerShape(99.dp)) {
                        Text(if (connected == true) "● 已联通" else "● 未联通", Modifier.padding(horizontal = 11.dp, vertical = 6.dp), color = if (connected == true) Forest else Color(0xFF9A433A), style = MaterialTheme.typography.labelSmall)
                    }
                    Spacer(Modifier.width(12.dp))
                })
            },
            bottomBar = {
                NavigationBar {
                    NavigationBarItem(selected = selectedTab == 0, onClick = { selectedTab = 0 }, icon = { Text("✦") }, label = { Text("会话") })
                    NavigationBarItem(selected = selectedTab == 1, onClick = { selectedTab = 1 }, icon = { Text("▤") }, label = { Text("采集") })
                    NavigationBarItem(selected = selectedTab == 2, onClick = { selectedTab = 2 }, icon = { Text("▣") }, label = { Text("文件") })
                    NavigationBarItem(selected = selectedTab == 3, onClick = { selectedTab = 3 }, icon = { Text("⚙") }, label = { Text("设置") })
                }
            }
        ) { padding ->
            Column(Modifier.fillMaxSize().padding(padding).background(Paper)) {
                Text(notice, Modifier.fillMaxWidth().background(if (connected == true) Color(0xFFE6EEE8) else Color(0xFFF2E7E2)).padding(horizontal = 16.dp, vertical = 9.dp), style = MaterialTheme.typography.bodySmall)
                when (selectedTab) {
                    0 -> ConversationScreen(server, chats, mapConfig, draft, { draft = it }, sending, uploading, onSend = {
                        val message = draft.trim()
                        if (message.isNotEmpty()) {
                            draft = ""
                            sending = true
                            notice = "正在发送并等待回复…"
                            scope.launch {
                                runCatching { ApiClient.sendChat(server, token, message) }
                                    .onSuccess {
                                        notice = "发送成功，电脑端也会同步显示"
                                        val updated = ApiClient.chats(server, token)
                                        chats = updated
                                        // A map attachment can be created by this very reply.  Fetch the
                                        // computer's AMap configuration at the same time; otherwise the
                                        // card incorrectly remains in the "no key" state until a later
                                        // manual refresh.
                                        if (updated.any { it.maps.isNotEmpty() }) {
                                            runCatching { ApiClient.mapConfig(server, token) }
                                                .onSuccess { mapConfig = it }
                                                .onFailure { notice = "地图配置读取失败：${it.message}" }
                                        }
                                    }
                                    .onFailure { SyncWorker.enqueueChat(context, server.trimEnd('/'), token, message); notice = "电脑暂时不可达，消息已进入离线队列" }
                                sending = false
                            }
                        }
                    }, onPickFiles = { filePicker.launch(arrayOf("*/*")) })
                    1 -> EventsScreen(events, onRefresh = { scope.launch { refresh() } })
                    2 -> FilesScreen(files, uploading, onPickFiles = { filePicker.launch(arrayOf("*/*")) }, onDelete = { deleteTarget = it })
                    else -> SettingsScreen(server, { server = it }, pairingCode, { pairingCode = it }, token.isNotBlank(), connected, usage, notificationStatus, onSave = {
                        server = server.trim().trimEnd('/')
                        preferences.edit().putString("server", server).apply()
                        scope.launch {
                            if (pairingCode.isNotBlank()) {
                                notice = "正在安全配对…"
                                val result = runCatching { ApiClient.pair(server, pairingCode.trim(), "${Build.MANUFACTURER} ${Build.MODEL}") }
                                result
                                    .onSuccess { newToken ->
                                        token = newToken
                                        pairingCode = ""
                                        preferences.edit().putString("access_token", newToken).apply()
                                        notice = "配对成功"
                                    }
                                    .onFailure { notice = "配对失败：${it.message}" }
                                if (result.isFailure) return@launch
                            }
                            refresh()
                        }
                    }, onNotifications = { context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }, onLocation = {
                        locationPermission.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
                    }, onCalendar = {
                        if (context.checkSelfPermission(Manifest.permission.READ_CALENDAR) == PackageManager.PERMISSION_GRANTED) syncCalendar()
                        else calendarPermission.launch(Manifest.permission.READ_CALENDAR)
                    })
                }
            }
        }
    }
}

@Composable
private fun ConversationScreen(server: String, chats: List<ChatExchange>, mapConfig: MapConfig?, draft: String, onDraft: (String) -> Unit, sending: Boolean, uploading: Boolean, onSend: () -> Unit, onPickFiles: () -> Unit) {
    val listState = rememberLazyListState()
    LaunchedEffect(chats.size, chats.lastOrNull()?.assistant) {
        if (chats.isNotEmpty()) listState.scrollToItem(chats.lastIndex)
    }
    Column(Modifier.fillMaxSize().padding(horizontal = 14.dp, vertical = 10.dp)) {
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = listState, verticalArrangement = Arrangement.spacedBy(9.dp), contentPadding = PaddingValues(vertical = 8.dp)) {
            if (chats.isEmpty()) item { Text("这里会实时显示手机和电脑两端的会话。", color = Color.Gray, modifier = Modifier.padding(12.dp)) }
            items(chats, key = { it.id }) { chat ->
                MessageBubble(server, chat.user, true, emptyList(), mapConfig)
                MessageBubble(server, chat.assistant.ifBlank { "正在处理…" }, false, chat.maps, mapConfig)
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = onPickFiles, enabled = !uploading) { Text(if (uploading) "上传中" else "文件") }
            OutlinedTextField(draft, onDraft, Modifier.weight(1f), placeholder = { Text("输入消息…") }, maxLines = 4)
            Button(onClick = onSend, enabled = draft.isNotBlank() && !sending) { Text(if (sending) "…" else "发送") }
        }
    }
}

@Composable
private fun MessageBubble(server: String, text: String, fromUser: Boolean, maps: List<MapSpec>, mapConfig: MapConfig?) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (fromUser) Arrangement.End else Arrangement.Start) {
        Surface(color = if (fromUser) Forest else Color(0xFFFFFDF8), shape = RoundedCornerShape(15.dp), tonalElevation = if (fromUser) 0.dp else 1.dp, modifier = Modifier.widthIn(max = 310.dp)) {
            Column(Modifier.padding(horizontal = 14.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (fromUser) Text(text, color = Color.White, style = MaterialTheme.typography.bodyMedium)
                else MarkdownText(text)
                maps.forEach { spec -> AmapCard(server, spec, mapConfig) }
            }
        }
    }
}

@Composable
private fun MarkdownText(markdown: String) {
    val html = remember(markdown) { markdownToHtml(markdown) }
    AndroidView(
        modifier = Modifier.fillMaxWidth(),
        factory = { context ->
            TextView(context).apply {
                setTextColor(android.graphics.Color.rgb(38, 51, 45))
                textSize = 15f
                includeFontPadding = false
                linksClickable = true
                movementMethod = LinkMovementMethod.getInstance()
            }
        },
        update = { view -> view.text = Html.fromHtml(html, Html.FROM_HTML_MODE_COMPACT) },
    )
}

@Composable
private fun AmapCard(server: String, spec: MapSpec, config: MapConfig?) {
    var mapError by remember(spec, config) { mutableStateOf<String?>(null) }
    Card(colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F1E8)), modifier = Modifier.fillMaxWidth()) {
        Column {
            if (config?.apiKey.isNullOrBlank()) {
                Text("地图已命中，请先在电脑设置页填写高德地图 Key。", Modifier.padding(12.dp), style = MaterialTheme.typography.bodySmall)
            } else {
                val html = remember(spec, config) { amapHtml(spec, config!!) }
                AndroidView(
                    modifier = Modifier.fillMaxWidth().height(220.dp),
                    factory = { context ->
                        WebView(context).apply {
                            settings.javaScriptEnabled = true
                            settings.domStorageEnabled = true
                            // Some AMap assets are still served over HTTP on
                            // certain networks.  The card contains no local
                            // credentials and has a visible HTTPS fallback.
                            settings.mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
                            settings.cacheMode = WebSettings.LOAD_NO_CACHE
                            addJavascriptInterface(AmapStatusBridge { message -> mapError = message }, "SecondBrainMap")
                            webViewClient = object : WebViewClient() {
                                override fun shouldOverrideUrlLoading(view: WebView, url: String): Boolean {
                                    if (url.startsWith("https://uri.amap.com/")) {
                                        runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
                                        return true
                                    }
                                    return false
                                }
                            }
                            webChromeClient = object : WebChromeClient() {
                                override fun onConsoleMessage(message: android.webkit.ConsoleMessage): Boolean {
                                    val text = message.message()
                                    if (text.contains("USERKEY", ignoreCase = true) || text.contains("AMap", ignoreCase = true) && text.contains("error", ignoreCase = true)) {
                                        mapError = "高德地图初始化失败：$text"
                                    }
                                    return super.onConsoleMessage(message)
                                }
                            }
                            tag = html.hashCode()
                            // Keep the same origin as the paired server. AMap Web keys
                            // commonly whitelist that LAN origin; using webapi.amap.com
                            // as a fabricated origin leaves an empty bordered WebView.
                            loadDataWithBaseURL(server.trimEnd('/') + "/", html, "text/html", "UTF-8", null)
                        }
                    },
                    update = { view ->
                        if (view.tag != html.hashCode()) {
                            view.tag = html.hashCode()
                            view.loadDataWithBaseURL(server.trimEnd('/') + "/", html, "text/html", "UTF-8", null)
                        }
                    },
                )
            }
            mapError?.let { Text(it, Modifier.padding(horizontal = 11.dp, vertical = 4.dp), style = MaterialTheme.typography.labelSmall, color = Color(0xFF9A433A)) }
            Text(spec.query.ifBlank { spec.label.ifBlank { "位置地图" } }, Modifier.padding(horizontal = 11.dp, vertical = 8.dp), style = MaterialTheme.typography.labelSmall, color = Color.Gray)
        }
    }
}

private class AmapStatusBridge(private val onError: (String) -> Unit) {
    private val mainThread = Handler(Looper.getMainLooper())

    @JavascriptInterface
    fun reportError(message: String) {
        mainThread.post { onError(message) }
    }
}

private fun markdownToHtml(markdown: String): String {
    val output = mutableListOf<String>()
    var listType: String? = null
    var inCode = false
    fun closeList() { listType?.let { output += "</$it>" }; listType = null }
    val lines = markdown.replace("\r\n", "\n").replace('\r', '\n').lines()
    var index = 0
    while (index < lines.size) {
        val raw = lines[index]
        val line = raw.trimEnd()
        if (line.trimStart().startsWith("```")) {
            closeList()
            output += if (inCode) "</code></pre>" else "<pre><code>"
            inCode = !inCode
            index++
            continue
        }
        if (inCode) { output += Html.escapeHtml(line) + "\n"; index++; continue }
        if (index + 1 < lines.size && line.contains('|') && Regex("^\\s*\\|?\\s*:?-{3,}").containsMatchIn(lines[index + 1])) {
            closeList()
            val headers = markdownTableCells(line)
            index += 2
            while (index < lines.size && lines[index].contains('|') && lines[index].isNotBlank()) {
                val cells = markdownTableCells(lines[index])
                output += "<p>" + headers.mapIndexed { cellIndex, header ->
                    val value = cells.getOrNull(cellIndex).orEmpty()
                    "<b>${inlineMarkdownHtml(header)}：</b>${inlineMarkdownHtml(value)}"
                }.joinToString("　") + "</p>"
                index++
            }
            continue
        }
        val bullet = Regex("^\\s*[-*+]\\s+(.+)$").find(line)
        val ordered = Regex("^\\s*\\d+[.)]\\s+(.+)$").find(line)
        if (bullet != null || ordered != null) {
            val nextType = if (ordered != null) "ol" else "ul"
            if (listType != nextType) { closeList(); output += "<$nextType>"; listType = nextType }
            output += "<li>${inlineMarkdownHtml((bullet ?: ordered)!!.groupValues[1])}</li>"
            index++
            continue
        }
        closeList()
        if (line.isBlank()) { output += "<br>"; index++; continue }
        val heading = Regex("^(#{1,6})\\s+(.+)$").find(line)
        output += when {
            heading != null -> {
                val size = (7 - heading.groupValues[1].length).coerceIn(2, 5)
                "<h$size>${inlineMarkdownHtml(heading.groupValues[2])}</h$size>"
            }
            line.startsWith(">") -> "<blockquote>${inlineMarkdownHtml(line.removePrefix(">").trimStart())}</blockquote>"
            else -> "<div>${inlineMarkdownHtml(line)}</div>"
        }
        index++
    }
    closeList()
    if (inCode) output += "</code></pre>"
    return output.joinToString("")
}

private fun markdownTableCells(line: String): List<String> =
    line.trim().trim('|').split('|').map { it.trim() }

private fun inlineMarkdownHtml(value: String): String {
    var html = Html.escapeHtml(value)
    html = Regex("`([^`]+)`").replace(html, "<code>$1</code>")
    html = Regex("\\[([^]]+)]\\((https?://[^)]+)\\)").replace(html, "<a href=\"$2\">$1</a>")
    html = Regex("\\*\\*([^*]+)\\*\\*").replace(html, "<b>$1</b>")
    html = Regex("__([^_]+)__").replace(html, "<b>$1</b>")
    html = Regex("(?<!\\*)\\*([^*]+)\\*(?!\\*)").replace(html, "<i>$1</i>")
    return html
}

private fun amapHtml(spec: MapSpec, config: MapConfig): String {
    val encodedKey = URLEncoder.encode(config.apiKey, StandardCharsets.UTF_8.toString())
    val center = if (spec.longitude != null && spec.latitude != null) "[${spec.longitude},${spec.latitude}]" else "null"
    return """
        <!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><style>html,body,#map{width:100%;height:100%;margin:0;background:#eeeae1;font-family:sans-serif}#state{position:absolute;inset:0;z-index:9;display:grid;place-items:center;padding:24px;text-align:center;color:#526158;background:#f5f1e8}#state a{display:block;margin-top:12px;color:#315d49}</style></head>
        <body><div id="map"></div><div id="state">地图加载中…</div><script>
        window._AMapSecurityConfig={securityJsCode:${JSONObject.quote(config.securityCode)}};
        const state=document.getElementById('state'),center=$center,query=${JSONObject.quote(spec.query)};
        const fallback='https://uri.amap.com/search?keyword='+encodeURIComponent(query||${JSONObject.quote(spec.label.ifBlank { "当前位置" })})+(center?'&center='+center.join(','):'')+'&callnative=1';
        function fail(message){if(window.SecondBrainMap)SecondBrainMap.reportError(message);state.innerHTML=message+'<a href="'+fallback+'">在高德地图中打开 ↗</a>';state.style.display='grid'}
        function ready(){try{const map=new AMap.Map('map',{zoom:13,center:center||undefined});if(center)new AMap.Marker({position:center,map:map,title:${JSONObject.quote(spec.label.ifBlank { "当前位置" })}});if(query)AMap.plugin('AMap.PlaceSearch',()=>{const search=new AMap.PlaceSearch({map:map,pageSize:5});${if (spec.mode == "nearby") "if(center)search.searchNearBy(query,center,5000);else search.search(query);" else "search.search(query);"}});state.style.display='none'}catch(error){fail('地图初始化失败，请检查 Key 的域名白名单')}}</script>
        <script src="https://webapi.amap.com/maps?v=2.0&key=$encodedKey" onload="ready()" onerror="fail('地图资源加载失败，请检查手机网络')"></script>
        <script>setTimeout(()=>{if(state.style.display!=='none')fail('地图加载超时，请检查网络与高德 Key')},8000)</script></body></html>
    """.trimIndent()
}

@Composable
private fun EventsScreen(events: List<CollectedEvent>, onRefresh: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        SectionHeader("已采集内容", "短信、通知与只读日程按时间同步到电脑", "刷新", onRefresh)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(9.dp), contentPadding = PaddingValues(vertical = 12.dp)) {
            if (events.isEmpty()) item { Text("暂无记录。授权后可同步短信、通知和近期日程。", color = Color.Gray) }
            items(events, key = { it.id }) { event ->
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Text("${when (event.source) { "sms" -> "短信"; "calendar" -> "日程"; else -> "通知" }} · ${event.title}", style = MaterialTheme.typography.titleSmall)
                    Text(event.content, style = MaterialTheme.typography.bodyMedium)
                    Text(event.createdAt, style = MaterialTheme.typography.labelSmall, color = Color.Gray)
                } }
            }
        }
    }
}

@Composable
private fun FilesScreen(files: List<RemoteFile>, uploading: Boolean, onPickFiles: () -> Unit, onDelete: (RemoteFile) -> Unit) {
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        SectionHeader("上传记录", "手机和电脑上传的文件统一显示", if (uploading) "上传中" else "上传文件", onPickFiles)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(9.dp), contentPadding = PaddingValues(vertical = 12.dp)) {
            if (files.isEmpty()) item { Text("还没有上传记录。", color = Color.Gray) }
            items(files, key = { it.hash }) { file ->
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(file.name, style = MaterialTheme.typography.titleSmall)
                    Text(file.summary.ifBlank { "暂无分析结果" }, maxLines = 3, style = MaterialTheme.typography.bodySmall, color = Color.Gray)
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Text(file.createdAt, style = MaterialTheme.typography.labelSmall, color = Color.Gray)
                        TextButton(onClick = { onDelete(file) }) { Text("删除", color = Color(0xFFA04339)) }
                    }
                } }
            }
        }
    }
}

@Composable
private fun SectionHeader(title: String, subtitle: String, action: String, onAction: () -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Column { Text(title, style = MaterialTheme.typography.headlineSmall); Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Color.Gray) }
        TextButton(onClick = onAction) { Text(action) }
    }
}

@Composable
private fun SettingsScreen(server: String, onServer: (String) -> Unit, pairingCode: String, onPairingCode: (String) -> Unit, hasToken: Boolean, connected: Boolean?, usage: TokenActivity?, notificationStatus: String, onSave: () -> Unit, onNotifications: () -> Unit, onLocation: () -> Unit, onCalendar: () -> Unit) {
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(vertical = 20.dp)) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("连接电脑", style = MaterialTheme.typography.headlineSmall)
        OutlinedTextField(server, onServer, label = { Text("核心服务地址") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(pairingCode, onPairingCode, label = { Text(if (hasToken) "新配对码（重新配对时填写）" else "电脑端 6 位配对码") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        Button(onClick = onSave, modifier = Modifier.fillMaxWidth()) { Text(if (pairingCode.isBlank()) "保存并测试连接" else "保存并配对") }
        Text(if (connected == true) "已使用设备令牌安全访问电脑服务。" else "先在电脑 Web 设置页生成配对码，再在这里填写。请确保两台设备连接同一 Wi-Fi。", color = if (connected == true) Forest else Color(0xFF9A433A), style = MaterialTheme.typography.bodySmall)
            }
        }
        item { TokenActivityCard(usage) }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        HorizontalDivider()
        OutlinedButton(onClick = onLocation, enabled = connected == true, modifier = Modifier.fillMaxWidth()) { Text("上报一次当前位置") }
        Text("不会后台持续定位；只有点击这个按钮时才读取并上报 GPS。", style = MaterialTheme.typography.bodySmall, color = Color.Gray)
        OutlinedButton(onClick = onCalendar, enabled = connected == true, modifier = Modifier.fillMaxWidth()) { Text("读取并同步近期日程") }
        Text("仅在点击时申请日历读取权限，并只读取昨天至未来 14 天的日程；不会创建、修改或删除手机日历。", style = MaterialTheme.typography.bodySmall, color = Color.Gray)
        OutlinedButton(onClick = onNotifications, modifier = Modifier.fillMaxWidth()) { Text("开启通知读取权限") }
        Text(notificationStatus, style = MaterialTheme.typography.bodySmall, color = if (notificationStatus.startsWith("系统尚未")) Color(0xFF9A433A) else Forest)
        Text("短信权限在首次启动时申请；通知读取需要在系统页面单独开启。HyperOS 还应允许后台自启动，并将省电策略设为无限制。", style = MaterialTheme.typography.bodySmall, color = Color.Gray)
            }
        }
    }
}

@Composable
private fun TokenActivityCard(usage: TokenActivity?) {
    var mode by remember { mutableStateOf("每天") }
    val points = remember(usage, mode) {
        val days = usage?.days.orEmpty()
        when (mode) {
            "每周" -> days.chunked(7).mapIndexed { index, group ->
                TokenDay("第${index + 1}周", group.sumOf { it.tokens }, group.sumOf { it.cost })
            }.takeLast(16)
            "累计总量" -> days.groupBy { it.date.take(7) }.map { (month, group) ->
                TokenDay(month, group.sumOf { it.tokens }, group.sumOf { it.cost })
            }.takeLast(12)
            else -> days.takeLast(90).asReversed()
        }
    }
    val positiveLevels = remember(points) { points.map { it.tokens }.filter { it > 0 }.distinct().sorted() }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column { Text("Token 活动", style = MaterialTheme.typography.titleMedium); Text("${usage?.totalTokens ?: 0} tokens · ¥${"%.4f".format(usage?.totalCost ?: 0.0)}", style = MaterialTheme.typography.labelSmall, color = Color.Gray) }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("每天", "每周", "累计总量").forEach { label ->
                    if (mode == label) Button(onClick = { mode = label }, modifier = Modifier.weight(1f), contentPadding = PaddingValues(horizontal = 4.dp)) { Text(label, style = MaterialTheme.typography.labelSmall) }
                    else OutlinedButton(onClick = { mode = label }, modifier = Modifier.weight(1f), contentPadding = PaddingValues(horizontal = 4.dp)) { Text(label, style = MaterialTheme.typography.labelSmall) }
                }
            }
            if (usage == null) Text("连接电脑后显示用量", color = Color.Gray, style = MaterialTheme.typography.bodySmall)
            else LazyRow(horizontalArrangement = Arrangement.spacedBy(5.dp), contentPadding = PaddingValues(vertical = 3.dp)) {
                items(points) { point ->
                    val strength = tokenActivityLevel(point.tokens, positiveLevels)
                    val color = listOf(Color(0xFFEBECE9), Color(0xFFCDE2D6), Color(0xFF8EBCA3), Color(0xFF4D8B6C), Color(0xFF1F6044))[strength]
                    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Box(Modifier.size(if (mode == "每天") 13.dp else 22.dp).background(color, RoundedCornerShape(3.dp)))
                        if (mode != "每天") Text(point.date.takeLast(if (mode == "累计总量") 2 else 4), style = MaterialTheme.typography.labelSmall, color = Color.Gray)
                    }
                }
            }
            Text("颜色越深，用量越高；费用按电脑端配置的模型价格估算。", style = MaterialTheme.typography.labelSmall, color = Color.Gray)
        }
    }
}

private fun tokenActivityLevel(value: Long, positiveLevels: List<Long>): Int {
    if (value <= 0 || positiveLevels.isEmpty()) return 0
    if (positiveLevels.size == 1) return 2
    if (positiveLevels.size == 2) return if (value <= positiveLevels.first()) 2 else 3
    if (positiveLevels.size == 3) return positiveLevels.indexOfFirst { it >= value }.coerceAtLeast(0) + 1
    val rank = positiveLevels.indexOfFirst { it >= value }.coerceAtLeast(0).toDouble() / (positiveLevels.size - 1)
    return when {
        rank < 0.25 -> 1
        rank < 0.5 -> 2
        rank < 0.75 -> 3
        else -> 4
    }
}
