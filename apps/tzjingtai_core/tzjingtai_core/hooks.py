app_name = "tzjingtai_core"
app_title = "Tzjingtai Core"
app_publisher = "台州京泰"
app_description = "台州京泰 ERPNext 通用定制（非承兑汇票业务的公共扩展容器）"
app_email = "dev@tzjingtai.com"
app_license = "MIT"

# 应用依赖
required_apps = ["frappe", "erpnext"]

# include js in doctype views
doctype_js = {
	"Item": "public/js/item.js",
}

# DocType 事件钩子
doc_events = {
	"Item": {
		"before_insert": "tzjingtai_core.overrides.item.set_item_code_by_group",
	},
}
