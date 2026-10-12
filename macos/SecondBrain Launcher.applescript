-- A small macOS app wrapper around the project launcher. It waits for the
-- launcher to confirm the local service, then explicitly opens the workspace.
set launcherPath to "/Users/Apple/Documents/ChatGPT/ai-secretary/start-second-brain.command"
set workspaceURL to "http://127.0.0.1:8765"

try
	do shell script "/bin/zsh " & quoted form of launcherPath
	open location workspaceURL
	display notification "工作台已在浏览器中打开。" with title "SecondBrain"
on error errorMessage
	display dialog "第二大脑启动失败：" & errorMessage & return & return & "请检查项目是否仍位于 Documents/ChatGPT/ai-secretary。" with title "SecondBrain" buttons {"知道了"} default button "知道了" with icon stop
end try
