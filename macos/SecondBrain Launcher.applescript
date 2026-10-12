-- A small macOS app wrapper around the project launcher.  It deliberately
-- starts it in the background so Finder never opens a terminal window.
set launcherPath to "/Users/Apple/Documents/ChatGPT/ai-secretary/start-second-brain.command"

try
	do shell script "/bin/zsh " & quoted form of launcherPath & " >/dev/null 2>&1 &"
	display notification "正在启动本机服务，并将自动打开工作台。" with title "SecondBrain"
on error errorMessage
	display dialog "第二大脑启动失败：" & errorMessage & return & return & "请检查项目是否仍位于 Documents/ChatGPT/ai-secretary。" with title "SecondBrain" buttons {"知道了"} default button "知道了" with icon stop
end try
