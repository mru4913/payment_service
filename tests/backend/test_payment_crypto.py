"""支付验签与解密纯函数测试"""

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.payments.alipay import verify_alipay_notify_rsa2
from backend.payments.wechat import decrypt_wechat_notify_resource


def test_verify_alipay_notify_rsa2_roundtrip():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )

    params = {
        "out_trade_no": "abc",
        "total_amount": "1.00",
        "trade_status": "TRADE_SUCCESS",
        "fund_bill_list": "[{}]",
    }
    items = sorted((k, v) for k, v in params.items())
    content = "&".join(f"{k}={v}" for k, v in items)
    sig = private_key.sign(
        content.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    params["sign"] = base64.b64encode(sig).decode("ascii")

    assert verify_alipay_notify_rsa2(params, params["sign"], public_pem) is True


def test_decrypt_wechat_notify_resource():
    key = b"1" * 32
    aesgcm = AESGCM(key)
    nonce = b"\x00" * 12
    ad = b"transaction"
    plain = json.dumps(
        {"out_trade_no": "x", "transaction_id": "y", "trade_state": "SUCCESS"}
    ).encode("utf-8")
    ct = aesgcm.encrypt(nonce, plain, ad)

    resource = {
        "algorithm": "AEAD_AES_256_GCM",
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "associated_data": "transaction",
        "ciphertext": base64.b64encode(ct).decode("ascii"),
    }
    out = decrypt_wechat_notify_resource(resource, key.decode("utf-8"))
    assert out["out_trade_no"] == "x"
    assert out["trade_state"] == "SUCCESS"


def test_decrypt_wechat_wrong_key_length():
    with pytest.raises(ValueError, match="32"):
        decrypt_wechat_notify_resource(
            {
                "nonce": base64.b64encode(b"\x00" * 12).decode(),
                "associated_data": "",
                "ciphertext": base64.b64encode(b"x").decode(),
            },
            "short",
        )
