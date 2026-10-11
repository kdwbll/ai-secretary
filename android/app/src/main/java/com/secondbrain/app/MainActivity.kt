package com.secondbrain.app

import android.Manifest
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.Html
import android.text.method.LinkMovementMethod
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
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

class MainActivity : ComponentActivity() {
    private val requestPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val permissions = mutableListOf(Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS)
        if (Build.VERSION.SDK_INT >= 33) permissions += Manifest.permission.POST_NOTIFICATIONS
        requestPermissions.launch(permissions.toTypedArray())
        setContent { SecondBrainApp(intent) }
    }
}

private val Forest = Color(0xFF315D49)
private val Paper = Color(0xFFF5F1E8)

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
        connected = ApiClient.health(server, token)
        if (connected == true) {
            notice = "已安全联通电脑 · 数据自动同步"
            runCatching { ApiClient.chats(server, token) }.onSuccess { updated ->
                chats = updated
                if (mapConfig == null && updated.any { it.maps.isNotEmpty() }) {
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

    LaunchedEffect(server, token) {
        while (isActive) {
            refresh()
            delay(2500)
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
                                    .onSuccess { notice = "发送成功，电脑端也会同步显示"; chats = ApiClient.chats(server, token) }
                                    .onFailure { SyncWorker.enqueueChat(context, server.trimEnd('/'), token, message); notice = "电脑暂时不可达，消息已进入离线队列" }
                                sending = false
                            }
                        }
                    }, onPickFiles = { filePicker.launch(arrayOf("*/*")) })
                    1 -> EventsScreen(events, onRefresh = { scope.launch { refresh() } })
                    2 -> FilesScreen(files, uploading, onPickFiles = { filePicker.launch(arrayOf("*/*")) }, onDelete = { deleteTarget = it })
                    else -> SettingsScreen(server, { server = it }, pairingCode, { pairingCode = it }, token.isNotBlank(), connected, usage, onSave = {
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
                            webViewClient = WebViewClient()
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
            Text(spec.query.ifBlank { spec.label.ifBlank { "位置地图" } }, Modifier.padding(horizontal = 11.dp, vertical = 8.dp), style = MaterialTheme.typography.labelSmall, color = Color.Gray)
        }
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
        function fail(message){state.innerHTML=message+'<a href="'+fallback+'">在高德地图中打开 ↗</a>';state.style.display='grid'}
        function ready(){try{const map=new AMap.Map('map',{zoom:13,center:center||undefined});if(center)new AMap.Marker({position:center,map:map,title:${JSONObject.quote(spec.label.ifBlank { "当前位置" })}});if(query)AMap.plugin('AMap.PlaceSearch',()=>{const search=new AMap.PlaceSearch({map:map,pageSize:5});${if (spec.mode == "nearby") "if(center)search.searchNearBy(query,center,5000);else search.search(query);" else "search.search(query);"}});state.style.display='none'}catch(error){fail('地图初始化失败，请检查 Key 的域名白名单')}}</script>
        <script src="https://webapi.amap.com/maps?v=2.0&key=$encodedKey" onload="ready()" onerror="fail('地图资源加载失败，请检查手机网络')"></script>
        <script>setTimeout(()=>{if(state.style.display!=='none')fail('地图加载超时，请检查网络与高德 Key')},8000)</script></body></html>
    """.trimIndent()
}

@Composable
private fun EventsScreen(events: List<CollectedEvent>, onRefresh: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        SectionHeader("已采集内容", "短信与通知按时间同步到电脑", "刷新", onRefresh)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(9.dp), contentPadding = PaddingValues(vertical = 12.dp)) {
            if (events.isEmpty()) item { Text("暂无记录。只有授权后新收到的短信和通知会显示在这里。", color = Color.Gray) }
            items(events, key = { it.id }) { event ->
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Text("${if (event.source == "sms") "短信" else "通知"} · ${event.title}", style = MaterialTheme.typography.titleSmall)
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
private fun SettingsScreen(server: String, onServer: (String) -> Unit, pairingCode: String, onPairingCode: (String) -> Unit, hasToken: Boolean, connected: Boolean?, usage: TokenActivity?, onSave: () -> Unit, onNotifications: () -> Unit, onLocation: () -> Unit) {
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
        OutlinedButton(onClick = onNotifications, modifier = Modifier.fillMaxWidth()) { Text("开启通知读取权限") }
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
