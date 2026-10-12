-- A small macOS app wrapper around the project launcher.
--
-- Do not run the shell script through `do shell script`: an AppleScript app
-- can be denied access to the user's Documents folder even though Terminal has
-- permission. Asking Launch Services to open the .command file makes Terminal
-- run it under the user's normal terminal permissions instead.
set launcherPath to "/Users/Apple/Documents/ChatGPT/ai-secretary/start-second-brain.command"

try
	do shell script "/usr/bin/open " & quoted form of launcherPath
	display notification "正在启动，网页准备好后会自动打开。" with title "SecondBrain"
on error errorMessage
	display dialog "第二大脑启动器无法打开：" & errorMessage & return & return & "请检查项目是否仍位于 Documents/ChatGPT/ai-secretary。" with title "SecondBrain" buttons {"知道了"} default button "知道了" with icon stop
end try
