// 台州京泰 —— Item 编码辅助
// 真实流水号只在保存时由服务端调用 ERPNext Series 生成，表单里展示的是只读预览。
(function () {
    const AUTO_SEQUENCE_MODE = "Auto Sequence";
    const MANUAL_WITH_PREFIX_MODE = "Manual With Prefix";
    const AUTO_CODE_PATTERN = /^[A-Z](?:\([A-Z]+\))?-\d+$/;

    frappe.ui.form.on("Item", {
        refresh(frm) {
            apply_item_code_rules(frm);
        },

        item_group(frm) {
            apply_item_code_rules(frm);
        },
    });

    function should_replace_auto_preview(frm) {
        return !frm.doc.item_code || AUTO_CODE_PATTERN.test(frm.doc.item_code);
    }

    function should_replace_manual_prefix(frm) {
        return !frm.doc.item_code || frm.doc.item_code === frm.__last_manual_prefix;
    }

    function apply_item_code_rules(frm) {
        if (!frm.is_new()) {
            frm.set_df_property("item_code", "read_only", 1);
            return;
        }

        frm.set_df_property("item_code", "reqd", 1);

        if (!frm.doc.item_group) {
            frm.set_df_property("item_code", "read_only", 0);
            frm.set_df_property(
                "item_code",
                "description",
                __("Select Item Group first, then the system will decide how item code is handled.")
            );
            return;
        }

        const requestedItemGroup = frm.doc.item_group;
        frappe.call({
            method: "tzjingtai.item_code.get_item_code_context",
            args: {
                item_group: requestedItemGroup,
            },
            callback(r) {
                if (!r.message || !frm.is_new() || frm.doc.item_group !== requestedItemGroup) return;
                apply_item_code_context(frm, r.message);
            },
        });
    }

    function apply_item_code_context(frm, context) {
        if (context.mode === AUTO_SEQUENCE_MODE) {
            frm.set_df_property("item_code", "read_only", 1);
            frm.set_df_property(
                "item_code",
                "description",
                __("Item code will be assigned automatically when the item is saved.")
            );

            if (should_replace_auto_preview(frm) && context.preview) {
                frm.set_value("item_code", context.preview);
            }
            return;
        }

        if (context.mode === MANUAL_WITH_PREFIX_MODE) {
            frm.set_df_property("item_code", "read_only", 0);
            frm.set_df_property("item_code", "description", __("Code must start with {0}.", [context.prefix]));

            if (should_replace_manual_prefix(frm) && context.prefix) {
                frm.set_value("item_code", context.prefix);
            }
            frm.__last_manual_prefix = context.prefix || "";
            return;
        }

        frm.set_df_property("item_code", "read_only", 0);
        frm.set_df_property("item_code", "description", "");
    }
})();
