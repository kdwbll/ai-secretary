import unittest
from core.secretary.parsers import parse_sms


class SmsParserTests(unittest.TestCase):
    def test_bank_expense(self):
        event = parse_sms("您尾号1234信用卡于美团消费人民币36.80元")
        self.assertEqual(event.kind, "expense")
        self.assertEqual(event.amount, 36.8)
        self.assertEqual(event.card_tail, "1234")

    def test_pickup(self):
        event = parse_sms("您的快递已到菜鸟驿站，取件码 6-2-120")
        self.assertEqual(event.kind, "pickup")
        self.assertEqual(event.code, "6-2-120")

    def test_verification_code_is_ignored(self):
        self.assertTrue(parse_sms("验证码 381920，五分钟内有效").ignored)


if __name__ == "__main__":
    unittest.main()
