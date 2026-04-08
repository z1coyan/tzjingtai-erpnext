app_name = "acceptance"
app_title = "承兑汇票管理"
app_publisher = "台州京泰"
app_description = "基于新一代票据系统的承兑汇票全生命周期管理"
app_email = "dev@tzjingtai.com"
app_license = "MIT"

# 应用图标及颜色
app_icon = "octicon octicon-note"
app_color = "#3498db"

# 应用依赖
required_apps = ["frappe", "erpnext"]

# Desk 首页图标
add_to_apps_screen = [
	{
		"name": app_name,
		"logo": "/assets/acceptance/images/logo.svg",
		"title": app_title,
		"route": "/desk/acceptance",
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/acceptance/css/acceptance.css"
# app_include_js = "/assets/acceptance/js/acceptance.js"

# include js in doctype views
doctype_js = {
	"Sales Invoice": "public/js/sales_invoice.js",
	"Purchase Invoice": "public/js/purchase_invoice.js",
}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"acceptance.acceptance.doctype.bill_of_exchange.bill_of_exchange.check_bill_maturity"
	],
}

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True
