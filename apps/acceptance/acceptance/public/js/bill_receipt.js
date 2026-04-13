// Bill Receipt form customizations:
//  - OCR button: call Aliyun OCR on the face image and auto-fill fields
//  - Auto-bring default accounts from Bill of Exchange Settings on new doc
//  - Party account resolution when from_party_type/from_party changes

frappe.ui.form.on("Bill Receipt", {
    refresh(frm) {
        if (!frm.is_new() && frm.doc.docstatus === 0 && frm.doc.face_image) {
            frm.add_custom_button(__("Recognize Front Image"), () => recognize_front(frm), __("OCR"));
        } else if (frm.doc.face_image) {
            frm.add_custom_button(__("Recognize Front Image"), () => recognize_front(frm), __("OCR"));
        }
    },

    onload(frm) {
        if (frm.is_new()) {
            if (!frm.doc.company) {
                const c = frappe.defaults.get_user_default("Company") || frappe.defaults.get_default("Company");
                if (c) frm.set_value("company", c);
            }
            frappe.db.get_single_value("Bill of Exchange Settings", "default_bill_receivable_account")
                .then((v) => { if (v) frm.set_value("debit_account", v); });
        }
    },

    face_image(frm) {
        frm.refresh();
    },

    from_party_type(frm) {
        frm.set_value("from_party", null);
        resolve_credit_account(frm);
    },

    from_party(frm) {
        resolve_credit_account(frm);
    },

    segment_from(frm) { auto_amount(frm); },
    segment_to(frm) { auto_amount(frm); },
});

function auto_amount(frm) {
    const f = parseInt(frm.doc.segment_from, 10);
    const t = parseInt(frm.doc.segment_to, 10);
    if (!Number.isFinite(f) || !Number.isFinite(t) || t < f) return;
    const calc = Math.round(((t - f + 1) / 100) * 100) / 100;
    if (!frm.doc.amount || Math.abs(flt(frm.doc.amount) - calc) > 0.001) {
        frm.set_value("amount", calc);
    }
}

function recognize_front(frm) {
    if (!frm.doc.face_image) {
        frappe.msgprint(__("Please upload a face image first"));
        return;
    }
    frappe.show_alert({ message: __("Calling Aliyun OCR..."), indicator: "blue" });
    frappe.call({
        method: "acceptance.api.ocr.recognize_bill_front",
        args: { file_url: frm.doc.face_image },
        freeze: true,
        freeze_message: __("Recognizing bill front image..."),
        callback: ({ message }) => {
            if (!message) {
                frappe.msgprint(__("OCR returned no data"));
                return;
            }
            const fields = [
                "bill_no",
                "bill_type",
                "drawer_name",
                "drawer_account_no",
                "drawee_bank",
                "payee_name",
                "issue_date",
                "maturity_date",
                "face_amount",
                "segment_from",
                "segment_to",
            ];
            let filled = 0;
            fields.forEach((f) => {
                if (message[f] !== null && message[f] !== undefined && message[f] !== "") {
                    frm.set_value(f, message[f]);
                    filled += 1;
                }
            });
            // 如果 OCR 回填了 face_amount 但用户还没手填 amount（典型：整张票一次性接收），
            // 默认把 amount 设为 face_amount，用户可改。
            if (message.face_amount && !frm.doc.amount) {
                frm.set_value("amount", message.face_amount);
            }
            if (filled === 0) {
                frappe.msgprint({
                    title: __("OCR returned no recognizable fields"),
                    message: __("Check Error Log for the raw Aliyun response; verify the image is a bill front image."),
                    indicator: "orange",
                });
            } else {
                frappe.show_alert({
                    message: __("OCR filled {0} fields. Please manually enter sub-segment ranges.", [filled]),
                    indicator: "green",
                });
            }
        },
    });
}

function resolve_credit_account(frm) {
    if (!frm.doc.from_party_type || !frm.doc.from_party || !frm.doc.company) return;
    frappe.call({
        method: "erpnext.accounts.party.get_party_account",
        args: {
            party_type: frm.doc.from_party_type,
            party: frm.doc.from_party,
            company: frm.doc.company,
        },
        callback: ({ message }) => {
            if (message) frm.set_value("credit_account", message);
        },
    });
}
