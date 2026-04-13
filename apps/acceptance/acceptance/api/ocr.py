"""阿里云 OCR 承兑汇票正面识别。

用户在 Bill Receipt 表单点 "Recognize Front Image" 按钮时，前端 frappe.call 调用本方法。
实现上直接用 requests 走阿里云 OpenAPI 签名流程，避免引入巨大的 alibabacloud SDK。
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import re
import uuid
from urllib.parse import quote

import frappe
import requests
from frappe import _


ALIYUN_OCR_HOST = "ocr-api.cn-hangzhou.aliyuncs.com"
ALIYUN_OCR_VERSION = "2021-07-07"
ALIYUN_OCR_ACTION = "RecognizeBankAcceptance"


def _get_settings():
    settings = frappe.get_cached_doc("Bill of Exchange Settings")
    if not settings.ocr_enabled:
        frappe.throw(_("OCR is not enabled in Bill of Exchange Settings"))
    if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
        frappe.throw(_("Aliyun access key is not configured in Bill of Exchange Settings"))
    return settings


def _read_file_bytes(file_url: str) -> bytes:
    from frappe.utils.file_manager import get_file

    _name, content = get_file(file_url)
    if isinstance(content, str):
        content = content.encode("latin-1")
    return content


def _percent_encode(value: str) -> str:
    return quote(str(value), safe="-._~")


def _sign_v1(params: dict, secret: str) -> str:
    sorted_items = sorted(params.items())
    canonical = "&".join(f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted_items)
    string_to_sign = "POST&%2F&" + _percent_encode(canonical)
    key = (secret + "&").encode("utf-8")
    digest = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _call_aliyun_ocr(image_bytes: bytes, ak: str, sk: str) -> dict:
    body = image_bytes
    common = {
        "Format": "JSON",
        "Version": ALIYUN_OCR_VERSION,
        "AccessKeyId": ak,
        "SignatureMethod": "HMAC-SHA1",
        "Timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "SignatureVersion": "1.0",
        "SignatureNonce": uuid.uuid4().hex,
        "Action": ALIYUN_OCR_ACTION,
    }
    signature = _sign_v1(common, sk)
    common["Signature"] = signature
    url = f"https://{ALIYUN_OCR_HOST}/?" + "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in common.items()
    )
    resp = requests.post(url, data=body, headers={"Content-Type": "application/octet-stream"}, timeout=30)
    if resp.status_code != 200:
        frappe.log_error(resp.text, "Aliyun OCR HTTP error")
        frappe.throw(_("Aliyun OCR request failed: {0}").format(resp.status_code))
    try:
        return resp.json()
    except Exception:
        frappe.log_error(resp.text, "Aliyun OCR JSON parse error")
        frappe.throw(_("Aliyun OCR returned invalid JSON"))


_DATE_RX = re.compile(r"(20\d{2})\s*[年./\-]\s*(\d{1,2})\s*[月./\-]\s*(\d{1,2})")
_AMOUNT_RX = re.compile(r"([\d,]+(?:\.\d{1,2})?)")
# subDraftNumber 通常形如 "00000001-00000050" 或 "00000001~00000050" 或全中文连字符
_SUB_DRAFT_RX = re.compile(r"(\d{3,})\s*[-~—至到]\s*(\d{3,})")


def _pick(d: dict, *keys: str) -> str | None:
    """按顺序尝试多个 key，返回第一个非空字符串值。"""
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def _normalize_date(text: str | None) -> str | None:
    if not text:
        return None
    m = _DATE_RX.search(text)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def _normalize_amount(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = text.replace(",", "").replace("¥", "").replace("￥", "").strip()
    m = _AMOUNT_RX.search(cleaned)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _classify_bill_type(acceptor_name: str | None) -> str | None:
    """根据承兑人（acceptorName）判断是银票还是商票。

    RecognizeBankAcceptance 没有专门的 bill_type 字段，需要靠承兑人名称推断：
    承兑人含"银行" → 银承；其他 → 商承。
    """
    if not acceptor_name:
        return None
    if "银行" in acceptor_name:
        return "Bank Acceptance Bill"
    return "Commercial Acceptance Bill"


def _parse_sub_draft_range(sub: str | None) -> tuple[str | None, str | None]:
    if not sub:
        return None, None
    m = _SUB_DRAFT_RX.search(sub)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _parse_ocr_data(payload: dict) -> dict:
    """把阿里云 RecognizeBankAcceptance 的响应归一化为业务字段。

    阿里云的真实响应形如：
      {"RequestId": "...",
       "Data": "{\"data\": {\"票据号码\":\"1234...\", \"出票日期\":\"2024年01月01日\", ...},
                 \"prism_wordsInfo\": [...]}"}
    Data 是 **JSON 字符串**，需先 loads；真正字段藏在 .data 子对象里，key 全是中文。
    """
    import json as _json

    data_raw = payload.get("Data") or payload.get("data") or {}
    if isinstance(data_raw, str):
        try:
            data_raw = _json.loads(data_raw)
        except Exception:
            data_raw = {}
    # 阿里云响应的主字段块通常在 Data.data 下；兼容少量变体把整个 Data 当字段块。
    fields = {}
    if isinstance(data_raw, dict):
        if isinstance(data_raw.get("data"), dict):
            fields = data_raw["data"]
        else:
            fields = data_raw
    return fields if isinstance(fields, dict) else {}


@frappe.whitelist()
def recognize_bill_front(file_url: str) -> dict:
    """识别承兑汇票正面图，返回可用于 frm.set_value 的字段字典。

    注意：阿里云承兑识别不会返回"子票区间（起止票号）"——这些是业务方按客户/金额
    自行拆分的业务数据，并不印在票面上。OCR 只能填主票的字段，子票段需用户手动录入。
    """
    if not file_url:
        frappe.throw(_("file_url is required"))
    settings = _get_settings()
    ak = settings.aliyun_access_key_id
    sk = settings.get_password("aliyun_access_key_secret", raise_exception=False)
    if not sk:
        frappe.throw(_("Aliyun access key secret is not set"))

    try:
        image_bytes = _read_file_bytes(file_url)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "OCR read file failed")
        frappe.throw(_("Failed to read file: {0}").format(e))

    payload = _call_aliyun_ocr(image_bytes, ak, sk)
    fields = _parse_ocr_data(payload)

    if not fields:
        frappe.log_error(frappe.as_json(payload)[:2000], "OCR empty data")

    # 字段名来自阿里云 RecognizeBankAcceptance 官方文档（2021-07-07 版本）
    acceptor_name = _pick(fields, "acceptorName")
    sub_raw = _pick(
        fields,
        "subDraftNumber",
        "subDraftNum",
        "childDraftNumber",
        "subBillNumber",
        "subBillRange",
        "subNo",
    )
    segment_from, segment_to = _parse_sub_draft_range(sub_raw)

    # 诊断：解析不到子票区间时把所有字段 key 写到 Error Log，便于定位实际 key 名
    if not segment_from and not segment_to and isinstance(fields, dict):
        try:
            diag = {
                "keys": list(fields.keys()),
                "sub_raw": sub_raw,
                "sample": {k: fields.get(k) for k in list(fields.keys())[:60]},
            }
            frappe.log_error(frappe.as_json(diag)[:8000], "OCR subDraftNumber missing")
        except Exception:
            pass

    result = {
        "bill_no": _pick(fields, "draftNumber"),
        "drawer_name": _pick(fields, "issuerName"),
        "drawer_account_no": _pick(fields, "issuerAccountNumber"),
        "payee_name": _pick(fields, "payeeName"),
        "drawee_bank": acceptor_name or _pick(fields, "acceptorAccountBank"),
        "issue_date": _normalize_date(_pick(fields, "issueDate")),
        "maturity_date": _normalize_date(_pick(fields, "validToDate")),
        "face_amount": _normalize_amount(_pick(fields, "totalAmount")),
        "bill_type": _classify_bill_type(acceptor_name),
        "segment_from": segment_from,
        "segment_to": segment_to,
    }
    return result
