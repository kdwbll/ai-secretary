package com.secondbrain.app

import android.Manifest
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

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

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun SecondBrainApp(intent: Intent?) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var server by remember { mutableStateOf(context.getSharedPreferences("second_brain", Context.MODE_PRIVATE).getString("server", "http://192.168.1.2:8765") ?: "http://192.168.1.2:8765") }
    var message by remember { mutableStateOf(intent?.getStringExtra(Intent.EXTRA_TEXT) ?: "") }
    MaterialTheme(colorScheme = lightColorScheme(primary = androidx.compose.ui.graphics.Color(0xFF315D49))) {
        Scaffold(topBar = { TopAppBar(title = { Text("第二大脑") }) }) { padding ->
            Column(Modifier.padding(padding).padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Text("连接你的电脑", style = MaterialTheme.typography.headlineSmall)
                OutlinedTextField(server, { server = it }, label = { Text("核心服务地址") }, modifier = Modifier.fillMaxWidth())
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(onClick = {
                        context.getSharedPreferences("second_brain", Context.MODE_PRIVATE).edit().putString("server", server.trimEnd('/')).apply()
                    }) { Text("保存连接地址") }
                    OutlinedButton(onClick = { context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }) { Text("开启通知读取") }
                }
                Text("分享到这里的文字会先进入本机离线队列，连上电脑后自动同步。", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(message, { message = it }, label = { Text("记录或提问") }, modifier = Modifier.fillMaxWidth().height(140.dp))
                Button(onClick = {
                    val cleanServer = server.trimEnd('/')
                    context.getSharedPreferences("second_brain", Context.MODE_PRIVATE).edit().putString("server", cleanServer).apply()
                    SyncWorker.enqueueChat(context, cleanServer, message)
                }, enabled = message.isNotBlank()) { Text("发送到第二大脑") }
            }
        }
    }
}
