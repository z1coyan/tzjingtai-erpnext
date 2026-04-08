// Copyright (c) 2026, 台州京泰 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bill Receive", {
	refresh(frm) {
		// 草稿状态显示 OCR 识别按钮
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("OCR Recognition"), function () {
				recognize_bill(frm);
			}, __("Tools"));
		}
	},

	bill_amount(frm) {
		calculate_sub_ticket_end(frm);
	},

	sub_ticket_start(frm) {
		calculate_sub_ticket_end(frm);
	},

	front_image(frm) {
		if (frm.doc.front_image) {
			frappe.confirm(
				__("Front image uploaded. Run OCR recognition now?"),
				() => recognize_bill_front_only(frm)
			);
		}
	},
});

function calculate_sub_ticket_end(frm) {
	// 不可拆分票据（起始号为0），不自动计算
	if (!frm.doc.sub_ticket_start || frm.doc.sub_ticket_start === 0) {
		return;
	}
	if (frm.doc.bill_amount && frm.doc.sub_ticket_start > 0) {
		let count = Math.round(frm.doc.bill_amount / 0.01);
		frm.set_value("sub_ticket_end", frm.doc.sub_ticket_start + count - 1);
	}
}

function recognize_bill(frm) {
	if (!frm.doc.front_image && !frm.doc.back_image) {
		frappe.msgprint(__("Please upload front or back image first"));
		return;
	}

	frappe.show_progress(__("OCR Recognition..."), 0, 100, __("Calling Aliyun OCR service"));

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
	frappe.show_progress(__("OCR Recognition..."), 0, 100, __("Recognizing bill front"));

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
			sub_ticket_start: front.sub_ticket_start,
		};

		for (const [fieldname, value] of Object.entries(field_map)) {
			if (value !== null && value !== undefined && value !== "" && frm.fields_dict[fieldname]) {
				frm.set_value(fieldname, value);
				filled_count++;
			}
		}

		// 设置金额：优先使用 OCR 返回的金额，其次从子票区间计算
		if (front.amount) {
			frm.set_value("bill_amount", front.amount);
			filled_count++;
		} else if (front.sub_ticket_start && front.sub_ticket_end) {
			let amount = (front.sub_ticket_end - front.sub_ticket_start + 1) * 0.01;
			frm.set_value("bill_amount", amount);
			filled_count++;
		}

		// 标记低置信度字段
		if (front._confidence) {
			highlight_low_confidence_fields(frm, front._confidence);
		}

		frappe.show_alert({
			message: __("Front recognition complete, {0} fields filled", [filled_count]),
			indicator: "green",
		});
	}

	// 显示错误信息
	if (data.errors && data.errors.length > 0) {
		data.errors.forEach((err) => {
			frappe.msgprint({
				title: __("OCR Recognition Warning"),
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
			$field.attr("title", __("Low OCR confidence ({0}%), please verify", [prob]));
		} else if (prob < WARN_THRESHOLD) {
			$field.css("background-color", "#ffffcc");
			$field.attr("title", __("Moderate OCR confidence ({0}%), verification recommended", [prob]));
		}
	}
}
