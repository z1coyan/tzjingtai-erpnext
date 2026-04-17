(function () {
    const valueCache = new Map();

    const CONFIGS = [
        {
            parent: "Delivery Note",
            child: "Delivery Note Item",
            childTriggers: ["item_code", "against_sales_order"],
            resolve: async (frm, row) => {
                if (!row.against_sales_order) {
                    return "";
                }

                return get_cached_value("Sales Order", row.against_sales_order, "po_no");
            },
        },
        {
            parent: "Purchase Receipt",
            child: "Purchase Receipt Item",
            childTriggers: ["item_code", "purchase_order", "sales_order"],
            resolve: async (frm, row) => {
                if (row.purchase_order) {
                    return get_cached_value("Purchase Order", row.purchase_order, "order_confirmation_no");
                }

                if (row.sales_order) {
                    return get_cached_value("Sales Order", row.sales_order, "po_no");
                }

                return "";
            },
        },
        {
            parent: "Stock Entry",
            child: "Stock Entry Detail",
            parentTriggers: ["purchase_order", "subcontracting_order"],
            childTriggers: ["item_code"],
            resolve: async (frm, row) => {
                const purchaseOrder = await get_stock_entry_purchase_order(frm);
                if (!purchaseOrder) {
                    return "";
                }

                return get_cached_value("Purchase Order", purchaseOrder, "order_confirmation_no");
            },
        },
        {
            parent: "Subcontracting Receipt",
            child: "Subcontracting Receipt Item",
            parentTriggers: ["purchase_order"],
            childTriggers: ["item_code", "purchase_order", "subcontracting_order"],
            resolve: async (frm, row) => {
                const purchaseOrder =
                    row.purchase_order ||
                    frm.doc.purchase_order ||
                    (await get_subcontracting_order_purchase_order(row.subcontracting_order));

                if (!purchaseOrder) {
                    return "";
                }

                return get_cached_value("Purchase Order", purchaseOrder, "order_confirmation_no");
            },
        },
    ];

    for (const config of CONFIGS) {
        register_parent_handlers(config);
        register_child_handlers(config);
    }

    function register_parent_handlers(config) {
        const handlers = {
            items_add(frm, cdt, cdn) {
                void set_row_remark(frm, cdt, cdn, config);
            },
            onload_post_render(frm) {
                if (frm.is_new()) {
                    void update_all_rows(frm, config);
                }
            },
        };

        for (const eventName of config.parentTriggers || []) {
            handlers[eventName] = function (frm) {
                void update_all_rows(frm, config);
            };
        }

        frappe.ui.form.on(config.parent, handlers);
    }

    function register_child_handlers(config) {
        const handlers = {
            form_render(frm, cdt, cdn) {
                void set_row_remark(frm, cdt, cdn, config);
            },
        };

        for (const eventName of config.childTriggers || []) {
            handlers[eventName] = function (frm, cdt, cdn) {
                void set_row_remark(frm, cdt, cdn, config);
            };
        }

        frappe.ui.form.on(config.child, handlers);
    }

    async function update_all_rows(frm, config) {
        if (!can_auto_fill(frm, config.child)) {
            return;
        }

        for (const row of frm.doc.items || []) {
            await set_row_remark(frm, row.doctype, row.name, config);
        }
    }

    async function set_row_remark(frm, cdt, cdn, config) {
        if (!can_auto_fill(frm, config.child)) {
            return;
        }

        const row = locals[cdt] && locals[cdt][cdn];
        if (!row) {
            return;
        }

        const value = ((await config.resolve(frm, row)) || "").trim();
        if (!value || row.custom_remark === value) {
            return;
        }

        await frappe.model.set_value(cdt, cdn, "custom_remark", value);
    }

    function can_auto_fill(frm, childDoctype) {
        return frm.doc.docstatus === 0 && frappe.meta.has_field(childDoctype, "custom_remark");
    }

    async function get_stock_entry_purchase_order(frm) {
        if (frm.doc.purchase_order) {
            return frm.doc.purchase_order;
        }

        return get_subcontracting_order_purchase_order(frm.doc.subcontracting_order);
    }

    async function get_subcontracting_order_purchase_order(subcontractingOrder) {
        if (!subcontractingOrder) {
            return "";
        }

        return get_cached_value("Subcontracting Order", subcontractingOrder, "purchase_order");
    }

    async function get_cached_value(doctype, name, fieldname) {
        if (!name) {
            return "";
        }

        const cacheKey = [doctype, name, fieldname].join("::");
        if (!valueCache.has(cacheKey)) {
            const request = frappe.db
                .get_value(doctype, name, fieldname)
                .then((response) => (response.message && response.message[fieldname]) || "");
            valueCache.set(cacheKey, request);
        }

        return valueCache.get(cacheKey);
    }
})();
