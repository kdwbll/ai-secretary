package com.secondbrain.app

import android.app.Activity
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class PermissionsRationaleActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val density = resources.displayMetrics.density
        val padding = (24 * density).toInt()
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(padding, padding, padding, padding)
            addView(TextView(context).apply {
                text = "健康数据读取说明"
                textSize = 26f
                setTextColor(0xFF1F2924.toInt())
            }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            addView(TextView(context).apply {
                text = "\n第二大脑只读取你选择授权的步数、心率、睡眠、体重、活动能量和距离，用于在你的电脑上生成健康汇总并回答相关问题。\n\n应用不会写入、修改或删除 Health Connect 数据，也不会将数据发送到你配对电脑以外的服务。你可以随时在 Health Connect 中撤销权限。"
                textSize = 17f
                setTextColor(0xFF4B5A53.toInt())
                setLineSpacing(0f, 1.25f)
            }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            addView(Button(context).apply {
                text = "知道了"
                setOnClickListener { finish() }
            }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                topMargin = padding
            })
        }
        setContentView(container)
    }
}
