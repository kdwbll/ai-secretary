from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


@dataclass
class ParsedEvent:
    kind: str
    title: str
    amount: Optional[float] = None
    merchant: Optional[str] = None
    card_tail: Optional[str] = None
    time: Optional[str] = None
    code: Optional[str] = None
    location: Optional[str] = None
    ignored: bool = False
    raw: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


AMOUNT = r"(?:人民币|RMB|￥|¥)?\s*([\d,]+(?:\.\d{1,2})?)\s*元?"


def parse_sms(text: str, sender: str = "") -> ParsedEvent:
    raw = text.strip()
    if re.search(r"验证码|校验码|动态码", raw) and re.search(r"\b\d{4,8}\b", raw):
        return ParsedEvent("ignored", "验证码", ignored=True, raw=raw)
    if re.search(r"退订|推广|促销|营销", raw):
        return ParsedEvent("ignored", "营销短信", ignored=True, raw=raw)

    amount_match = re.search(r"(?:消费|支出|支付|扣款|交易).*?" + AMOUNT, raw)
    if not amount_match:
        amount_match = re.search(AMOUNT + r".*?(?:消费|支出|支付|扣款|交易)", raw)
    if amount_match:
        amount = float(amount_match.group(1).replace(",", ""))
        tail = re.search(r"(?:尾号|末四位)[为:]?\s*(\d{4})", raw)
        merchant = re.search(r"(?:商户|于|收款方)[：:]?\s*([^，。,；;]+)", raw)
        return ParsedEvent("expense", "消费记录", amount=amount, merchant=merchant.group(1).strip() if merchant else None, card_tail=tail.group(1) if tail else None, raw=raw)

    pickup = re.search(r"(?:取件码|提货码)[：:\s]*([A-Za-z0-9-]{3,})", raw)
    if pickup:
        location = re.search(r"(?:至|到|存放于|地址)[：:]?\s*([^，。,；;]+)", raw)
        return ParsedEvent("pickup", "快递待取", code=pickup.group(1), location=location.group(1).strip() if location else None, raw=raw)

    train = re.search(r"([A-Z]\d{1,4})次.*?(\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}).*?([\u4e00-\u9fff]+站).*?([\u4e00-\u9fff]+站)", raw)
    if train:
        return ParsedEvent("trip", f"火车 {train.group(1)}：{train.group(3)} → {train.group(4)}", time=train.group(2), raw=raw)

    if re.search(r"挂号|就诊|体检|疫苗|医院", raw) and re.search(r"预约|提醒|成功", raw):
        return ParsedEvent("health_appointment", "医疗预约", raw=raw)
    if re.search(r"账单|欠费|余额不足|还款", raw):
        amount = re.search(AMOUNT, raw)
        return ParsedEvent("bill", "账单提醒", amount=float(amount.group(1).replace(",", "")) if amount else None, raw=raw)
    return ParsedEvent("unknown", "未分类短信", raw=raw)


def parse_notification(package: str, title: str, text: str) -> ParsedEvent:
    combined = f"{title} {text}"
    if package in {"com.eg.android.AlipayGphone", "com.tencent.mm"} and re.search(r"支付|付款|收款", combined):
        event = parse_sms(combined, package)
        if event.kind == "expense":
            return event
    return ParsedEvent("notification", title or "应用通知", raw=combined)
