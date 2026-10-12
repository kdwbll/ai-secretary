# Windows 11 专用版使用说明

这个分支针对 Windows 11 做了免输命令启动、中文终端、带空格路径、后台服务、浏览器自动打开、日志和桌面快捷方式处理。脚本只用项目自身的相对路径，不包含开发者电脑路径。

## 第一次安装

1. 安装 64 位 Python 3.11 或更高版本，安装时勾选 **Add Python to PATH**。
2. 下载并解压本分支，路径尽量简短，例如 `D:\AI\ai-secretary`。
3. 双击 `安装第二大脑-Windows.cmd`。它会创建 `.venv`、安装依赖、初始化数据，并在桌面创建“第二大脑”快捷方式。
4. 双击桌面快捷方式或 `启动第二大脑-Windows.cmd`。

启动器会等待服务真正可用后再打开 `http://127.0.0.1:8765`。服务已运行时重复双击不会开启第二份进程。

## 手机连接

启动器默认监听可信局域网，方便 Android 伴侣连接。Windows 防火墙首次询问时只勾选“专用网络”，不要勾选公共网络。

在 PowerShell 中运行 `ipconfig`，找到当前 Wi-Fi 的 IPv4 地址，然后在手机 App 填写：

```text
http://电脑IPv4地址:8765
```

再到电脑网页的“设置 → 设备安全”生成一次性配对码。不要在路由器上把 8765 端口映射到公网。

如果只想让本机访问，可在项目目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_second_brain_windows.ps1 -LocalOnly
```

## 故障排查

- 浏览器打不开：查看 `data\server-windows-error.log`。
- 显示端口被占用：关闭已有服务，或先设置 `$env:SECOND_BRAIN_PORT=8766` 再运行启动脚本。
- 手机连接不上：确认手机与电脑在同一个可信 Wi-Fi，Windows 网络配置为“专用”，并允许 Python 通过专用网络防火墙。
- 脚本闪退：最新版入口会停留在窗口中。若仍立即关闭，请从 Windows Terminal 运行对应 `.cmd`，并提供窗口内容或 `data\server-windows-error.log`。

API Key、邮箱授权码和地图 Key 仍由应用加密后保存在本机；不要把 `data`、`memory`、`files` 目录上传到 Git。
