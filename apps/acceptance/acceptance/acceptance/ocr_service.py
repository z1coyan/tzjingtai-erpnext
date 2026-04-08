# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt

"""阿里云 OCR 服务集成模块

使用 RecognizeBankAcceptance 识别票据正面
使用 RecognizeGeneralStructure 识别票据背面（背书信息）
"""

import io
import json
import re

import frappe
from frappe import _


def _get_ocr_client():
	"""初始化阿里云 OCR 客户端（从 OCR Settings 读取凭证）"""
	from alibabacloud_ocr_api20210707.client import Client as OcrClient
	from alibabacloud_tea_openapi import models as open_api_models

	settings = frappe.get_single("OCR Settings")
	if not settings.enabled:
		frappe.throw(_("OCR is not enabled, please configure in OCR Settings"))

	access_key_id = settings.aliyun_access_key_id
	access_key_secret = settings.get_password(
		fieldname="aliyun_access_key_secret",
		raise_exception=True,
	)

	config = open_api_models.Config(
		access_key_id=access_key_id,
		access_key_secret=access_key_secret,
		endpoint=settings.ocr_endpoint or "ocr-api.cn-hangzhou.aliyuncs.com",
		region_id=settings.ocr_region_id or "cn-hangzhou",
	)
	return OcrClient(config)


def _get_file_content(file_url):
	"""从 Frappe 文件系统读取图片二进制内容"""
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	content = file_doc.get_content()
	return io.BytesIO(content)


@frappe.whitelist()
def recognize_bill(front_image=None, back_image=None):
	"""统一入口：识别票据正面和/或背面

	参数:
		front_image: 正面图片的 file_url
		back_image: 背面图片的 file_url

	返回:
		dict: {"front": {...}, "back": {...}, "errors": [...]}
	"""
	result = {"front": {}, "back": {}, "errors": []}

	if front_image:
		try:
			result["front"] = recognize_bill_front(front_image)
		except Exception as e:
			frappe.log_error(title="OCR front recognition failed", message=frappe.get_traceback())
			result["errors"].append({"side": "front", "message": str(e)})

	if back_image:
		settings = frappe.get_single("OCR Settings")
		if settings.back_recognition_enabled:
			try:
				result["back"] = recognize_bill_back(back_image)
			except Exception as e:
				frappe.log_error(title="OCR back recognition failed", message=frappe.get_traceback())
				result["errors"].append({"side": "back", "message": str(e)})

	return result


@frappe.whitelist()
def recognize_bill_front(file_url):
	"""识别票据正面 - 调用 RecognizeBankAcceptance"""
	from alibabacloud_ocr_api20210707 import models as ocr_models
	from alibabacloud_tea_util import models as util_models

	client = _get_ocr_client()
	body_stream = _get_file_content(file_url)

	request = ocr_models.RecognizeBankAcceptanceRequest(body=body_stream)
	runtime = util_models.RuntimeOptions(read_timeout=10000, connect_timeout=5000)

	response = client.recognize_bank_acceptance_with_options(request, runtime)
	data = json.loads(response.body.data)
	return _map_front_fields(data)


@frappe.whitelist()
def recognize_bill_back(file_url):
	"""识别票据背面 - 调用 RecognizeGeneralStructure"""
	from alibabacloud_ocr_api20210707 import models as ocr_models
	from alibabacloud_tea_util import models as util_models

	client = _get_ocr_client()
	body_stream = _get_file_content(file_url)

	settings = frappe.get_single("OCR Settings")
	keys = json.loads(
		settings.back_recognition_keys or '["背书人名称", "被背书人名称", "背书日期"]'
	)

	request = ocr_models.RecognizeGeneralStructureRequest(
		body=body_stream,
		keys=keys,
	)
	runtime = util_models.RuntimeOptions(read_timeout=30000, connect_timeout=5000)

	response = client.recognize_general_structure_with_options(request, runtime)
	data = json.loads(response.body.data)
	return _map_back_fields(data)


def _map_front_fields(data):
	"""将阿里云返回字段映射为 DocType 字段名"""
	# 阿里云 OCR 返回结构: 字段值在嵌套的 data["data"] 中
	fields = data.get("data", {}) if isinstance(data.get("data"), dict) else data

	# 从票据包号首位推断票据种类
	draft_number = fields.get("draftNumber", "")
	bill_type_map = {
		"5": "Bank Acceptance Bill",
		"6": "Commercial Acceptance Bill",
		"7": "Supply Chain Commercial Bill",
		"8": "Supply Chain Bank Bill",
	}
	bill_type = bill_type_map.get(draft_number[0], "") if draft_number else ""

	return {
		"bill_no": draft_number,
		"bill_type": bill_type,
		"issue_date": _parse_date(fields.get("issueDate")),
		"due_date": _parse_date(fields.get("validToDate")),
		"drawer_name": fields.get("issuerName", ""),
		"drawer_account": fields.get("issuerAccountNumber", ""),
		"drawer_bank": fields.get("issuerAccountBank", ""),
		"acceptor_name": fields.get("acceptorName", ""),
		"acceptor_account": fields.get("acceptorAccountNumber", ""),
		"acceptor_bank": fields.get("acceptorAccountBank", ""),
		"payee_name": fields.get("payeeName", ""),
		"amount": _parse_amount(fields.get("totalAmount")),
		"amount_in_words": fields.get("totalAmountInWords", ""),
		"non_transferable": "不可转让" in fields.get("assignability", ""),
		"sub_ticket_start": _parse_sub_ticket(fields.get("subDraftNumber", ""), 0),
		"sub_ticket_end": _parse_sub_ticket(fields.get("subDraftNumber", ""), 1),
		# 置信度信息（前端用于标记低置信度字段）
		"_confidence": _extract_confidence(data),
	}


def _map_back_fields(data):
	"""将背面 OCR 返回的 KV 信息映射为背书链数据"""
	kv_info = data.get("kvInfo", {}).get("data", {})
	endorsements = []

	endorsement = {
		"endorser_name": kv_info.get("背书人名称", ""),
		"endorsee_name": kv_info.get("被背书人名称", ""),
		"endorsement_date": _parse_date(kv_info.get("背书日期")),
	}
	if any(endorsement.values()):
		endorsements.append(endorsement)

	return {
		"endorsements": endorsements,
	}


def _parse_date(date_str):
	"""将 OCR 返回的日期字符串统一解析为 YYYY-MM-DD 格式"""
	if not date_str:
		return None
	date_str = date_str.strip()
	patterns = [
		(r"(\d{4})年(\d{1,2})月(\d{1,2})日", r"\1-\2-\3"),
		(r"(\d{4})-(\d{1,2})-(\d{1,2})", r"\1-\2-\3"),
		(r"(\d{4})(\d{2})(\d{2})", r"\1-\2-\3"),
	]
	for pattern, replacement in patterns:
		match = re.match(pattern, date_str)
		if match:
			return re.sub(pattern, replacement, date_str)
	return date_str


def _parse_sub_ticket(range_str, index):
	"""从 '135490852-135893859' 格式中提取起始号(index=0)或结束号(index=1)"""
	if not range_str or "-" not in range_str:
		return 0
	parts = range_str.split("-", 1)
	try:
		return int(parts[index])
	except (ValueError, IndexError):
		return 0


def _parse_amount(amount_str):
	"""将 OCR 返回的金额字符串解析为浮点数"""
	if not amount_str:
		return 0
	cleaned = re.sub(r"[^\d.]", "", str(amount_str))
	try:
		return float(cleaned)
	except ValueError:
		return 0


def _extract_confidence(data):
	"""提取各字段的置信度信息"""
	confidence = {}
	for item in data.get("prism_keyValueInfo", []):
		key = item.get("key", "")
		prob = item.get("valueProb", 0)
		confidence[key] = prob
	return confidence
