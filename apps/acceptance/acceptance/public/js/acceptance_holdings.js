// Shared helpers for Bill Transfer / Discount / Settlement:
//  - set_query filter on `bill` link: only Active / Partially Settled
//  - render "Current Holdings" HTML block from bill.segments
//
// Loaded by hooks.app_include_js so all three forms can reuse it.

window.acceptance = window.acceptance || {};

acceptance.bind_bill_link_filter = function (frm) {
    frm.set_query("bill", () => ({
        filters: { status: ["in", ["Active", "Partially Settled"]] },
    }));
};

acceptance.render_holdings = function (frm) {
    if (!frm.fields_dict.holdings_display) return;
    const wrap = frm.fields_dict.holdings_display.$wrapper;
    if (!frm.doc.bill) {
        wrap.html('<div class="text-muted small">' + __("Select a bill to see current holdings") + "</div>");
        return;
    }
    frappe.db.get_doc("Bill of Exchange", frm.doc.bill).then((doc) => {
        const segs = (doc.segments || []).filter((s) => (s.amount || 0) > 0);
        if (segs.length === 0) {
            wrap.html('<div class="text-muted small">' + __("No held segments on this bill") + "</div>");
            return;
        }
        const isLegacy = !!doc.is_legacy || !doc.is_electronic;
        let html = '<div class="small text-muted" style="margin-bottom:4px">';
        html += __("Bill {0} · Face {1} · Outstanding {2}", [
            doc.name,
            format_currency(doc.face_amount),
            format_currency(doc.outstanding_amount),
        ]);
        html += "</div>";
        html += '<table class="table table-bordered table-sm" style="margin-bottom:0">';
        if (isLegacy) {
            html += "<thead><tr><th>#</th><th>" + __("Amount") + "</th></tr></thead><tbody>";
            segs.forEach((s, i) => {
                html += `<tr><td>${i + 1}</td><td>${format_currency(s.amount)}</td></tr>`;
            });
        } else {
            html +=
                "<thead><tr><th>" +
                __("Segment From") +
                "</th><th>" +
                __("Segment To") +
                "</th><th>" +
                __("Amount") +
                "</th></tr></thead><tbody>";
            segs.forEach((s) => {
                html += `<tr><td>${frappe.utils.escape_html(s.segment_from || "")}</td><td>${frappe.utils.escape_html(
                    s.segment_to || ""
                )}</td><td>${format_currency(s.amount)}</td></tr>`;
            });
        }
        html += "</tbody></table>";
        wrap.html(html);
    });
};
