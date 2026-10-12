"""Keep device housekeeping notifications out of personal context."""
from __future__ import annotations


# SMS content is collected through the dedicated SMS receiver, so a persistent
# notification from the system SMS application is never useful as a duplicate.
NOISY_PACKAGES = {
    "android",
    "com.android.mms",
    "com.android.systemui",
    "com.android.settings",
    "com.google.android.gms",
}
NOISY_PACKAGE_PREFIXES = ("com.miui.", "com.xiaomi.")
NOISY_TEXT = (
    "正在运行",
    "正在运行中",
    "正在处理中",
    "正在处理",
    "点按即可了解详情或停止应用",
    "语音唤醒",
    "小爱正在运行",
    "查找正在处理",
    "服务正在运行",
)


def is_noise_notification(package: str, title: str, text: str) -> bool:
    """Return true only for system/foreground-service housekeeping notices.

    This intentionally does not filter normal app notifications by package:
    a payment, chat, delivery, or calendar alert from the same phone should
    still reach the personal timeline.
    """
    normalized_package = (package or "").strip().lower()
    if normalized_package in NOISY_PACKAGES or normalized_package.startswith(NOISY_PACKAGE_PREFIXES):
        return True
    combined = f"{title or ''} {text or ''}".replace(" ", "")
    return any(phrase.replace(" ", "") in combined for phrase in NOISY_TEXT)
