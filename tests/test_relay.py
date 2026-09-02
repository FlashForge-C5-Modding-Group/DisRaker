import unittest

from disraker.relay import _signature


class RelaySignatureTests(unittest.TestCase):
    def test_signature_is_stable_and_covers_timestamp_and_body(self):
        body = b'{"status":{}}'
        signature = _signature("secret", "100", "nonce", body)
        self.assertEqual(len(signature), 64)
        self.assertEqual(
            signature, _signature("secret", "100", "nonce", body))
        self.assertNotEqual(
            signature, _signature("secret", "101", "nonce", body))
        self.assertNotEqual(
            signature, _signature("secret", "100", "other", body))
        self.assertNotEqual(
            signature,
            _signature("secret", "100", "nonce", b'{"status":1}'))
