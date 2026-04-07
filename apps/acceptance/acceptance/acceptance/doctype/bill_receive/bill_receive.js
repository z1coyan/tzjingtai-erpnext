// Copyright (c) 2026, 台州京泰 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bill Receive", {
	refresh(frm) {
		// 草稿状态显示 OCR 识别按钮
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("OCR 识别"), function () {
				recognize_bill(frm);
			}, __("工具"));
		}
	},

	sub_ticket_start(frm) {
		calculate_amount(frm);
	},

	sub_ticket_end(frm) {
		calculate_amount(frm);
	},

	front_image(frm) {
		if (frm.doc.front_image) {
			frappe.confirm(
				__("已上传票据正面图片，是否立即进行 OCR 识别？"),
				() => recognize_bill_front_only(frm)
			);
		}
	},
});

function calculate_amount(frm) {
	if (frm.doc.sub_ticket_start === 0 && frm.doc.sub_ticket_end === 0) {
		// 不可拆分，金额手动输入
	} else if (frm.doc.sub_ticket_start > 0 && frm.doc.sub_ticket_end >= frm.doc.sub_ticket_start) {
		let amount = (frm.doc.sub_ticket_end - frm.doc.sub_ticket_start + 1) * 0.01;
		frm.set_value("bill_amount", amount);
	}
}

function recognize_bill(frm) {
	if (!frm.doc.front_image && !frm.doc.back_image) {
		frappe.msgprint(__("请先上传票据正面或背面图片"));
		return;
	}

	frappe.show_progress(__("OCR 识别中..."), 0, 100, __("正在调用阿里云 OCR 服务"));

	frappe.call({
		method: "acceptance.acceptance.ocr_service.recognize_bill",
		args: {
			front_image: frm.doc.front_image || null,
			back_image: frm.doc.back_image || null,
		},
		callback(r) {
			frappe.hide_progress();
			if (r.message) {
				fill_form_from_ocr(frm, r.message);
			}
		},
		error() {
			frappe.hide_progress();
		},
	});
}

function recognize_bill_front_only(frm) {
	frappe.show_progress(__("OCR 识别中..."), 0, 100, __("正在识别票据正面"));

	frappe.call({
		method: "acceptance.acceptance.ocr_service.recognize_bill",
		args: {
			front_image: frm.doc.front_image,
		},
		callback(r) {
			frappe.hide_progress();
			if (r.message) {
				fill_form_from_ocr(frm, r.message);
			}
		},
		error() {
			frappe.hide_progress();
		},
	});
}

function fill_form_from_ocr(frm, data) {
	let filled_count = 0;

	// 填入正面识别结果
	if (data.front) {
		const front = data.front;
		const field_map = {
			bill_no: front.bill_no,
			bill_type: front.bill_type,
			issue_date: front.issue_date,
			due_date: front.due_date,
			drawer_name: front.drawer_name,
			drawer_account: front.drawer_account,
			drawer_bank: front.drawer_bank,
			acceptor_name: front.acceptor_name,
			acceptor_account: front.acceptor_account,
			acceptor_bank: front.acceptor_bank,
		};

		for (const [fieldname, value] of Object.entries(field_map)) {
			if (value && frm.fields_dict[fieldname]) {
				frm.set_value(fieldname, value);
				filled_count++;
			}
		}

		// 如果有金额但没有子票区间，直接设置金额
		if (front.amount && (!frm.doc.sub_ticket_start && !frm.doc.sub_ticket_end)) {
			frm.set_value("bill_amount", front.amount);
		}

		// 标记低置信度字段
		if (front._confidence) {
			highlight_low_confidence_fields(frm, front._confidence);
		}

		frappe.show_alert({
			message: __("正面识别完成，已填入 {0} 个字段", [filled_count]),
			indicator: "green",
		});
	}

	// 显示错误信息
	if (data.errors && data.errors.length > 0) {
		data.errors.forEach((err) => {
			frappe.msgprint({
				title: __("OCR 识别警告"),
				message: err.message,
				indicator: "orange",
			});
		});
	}

	frm.dirty();
}

function highlight_low_confidence_fields(frm, confidence) {
	const WARN_THRESHOLD = 70;
	const DANGER_THRESHOLD = 50;

	// 阿里云字段名 → DocType 字段名映射
	const key_field_map = {
		draftNumber: "bill_no",
		issueDate: "issue_date",
		validToDate: "due_date",
		issuerName: "drawer_name",
		issuerAccountNumber: "drawer_account",
		issuerAccountBank: "drawer_bank",
		acceptorName: "acceptor_name",
		acceptorAccountNumber: "acceptor_account",
		acceptorAccountBank: "acceptor_bank",
		payeeName: "payee_name",
		totalAmount: "bill_amount",
	};

	for (const [ocr_key, prob] of Object.entries(confidence)) {
		const fieldname = key_field_map[ocr_key];
		if (!fieldname || !frm.fields_dict[fieldname]) continue;

		const $field = frm.fields_dict[fieldname].$wrapper;
		if (prob < DANGER_THRESHOLD) {
			$field.css("background-color", "#ffcccc");
			$field.attr("title", __("OCR 置信度较低 ({0}%)，请核对", [prob]));
		} else if (prob < WARN_THRESHOLD) {
			$field.css("background-color", "#ffffcc");
			$field.attr("title", __("OCR 置信度一般 ({0}%)，建议核对", [prob]));
		}
	}
}
