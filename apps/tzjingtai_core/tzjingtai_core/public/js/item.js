// 物料编码字段联动：
//   - item_group = "F(P) 客户产品"  → 必填，提示以 F(P) 开头
//   - 其它分组                      → 提示将自动生成，留空即可
// 真正的生成/校验在服务端 before_insert 钩子里完成，这里只是 UX。

const CUSTOMER_PRODUCT_GROUP = "F(P) 客户产品";
const CUSTOMER_PRODUCT_PREFIX = "F(P)";

frappe.ui.form.on("Item", {
	item_group(frm) {
		apply_item_code_hint(frm);
	},
	refresh(frm) {
		apply_item_code_hint(frm);
	},
});

function apply_item_code_hint(frm) {
	if (!frm.is_new()) {
		// 已存在的 Item 不改 item_code 字段行为
		return;
	}
	const is_customer_product = frm.doc.item_group === CUSTOMER_PRODUCT_GROUP;
	frm.set_df_property("item_code", "reqd", is_customer_product ? 1 : 0);
	frm.set_df_property(
		"item_code",
		"description",
		is_customer_product
			? __("Please enter an Item Code starting with {0}", [CUSTOMER_PRODUCT_PREFIX])
			: __("Leave blank to auto-generate based on Item Group")
	);
}
