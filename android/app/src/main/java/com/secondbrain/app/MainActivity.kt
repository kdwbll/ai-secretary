package com.secondbrain.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { SecondBrainApp(intent) }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun SecondBrainApp(intent: Intent?) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var server by remember { mutableStateOf("http://192.168.1.2:8765") }
    var message by remember { mutableStateOf(intent?.getStringExtra(Intent.EXTRA_TEXT) ?: "") }
    MaterialTheme(colorScheme = lightColorScheme(primary = androidx.compose.ui.graphics.Color(0xFF315D49))) {
        Scaffold(topBar = { TopAppBar(title = { Text("第二大脑") }) }) { padding ->
            Column(Modifier.padding(padding).padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Text("连接你的电脑", style = MaterialTheme.typography.headlineSmall)
                OutlinedTextField(server, { server = it }, label = { Text("核心服务地址") }, modifier = Modifier.fillMaxWidth())
                Text("分享到这里的文字会先进入本机离线队列，连上电脑后自动同步。", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(message, { message = it }, label = { Text("记录或提问") }, modifier = Modifier.fillMaxWidth().height(140.dp))
                Button(onClick = { SyncWorker.enqueue(context, server, message) }, enabled = message.isNotBlank()) { Text("发送到第二大脑") }
            }
        }
    }
}
