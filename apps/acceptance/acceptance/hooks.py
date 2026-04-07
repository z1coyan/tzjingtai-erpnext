app_name = "acceptance"
app_title = "承兑汇票管理"
app_publisher = "台州京泰"
app_description = "基于新一代票据系统的承兑汇票全生命周期管理"
app_email = "dev@tzjingtai.com"
app_license = "MIT"

# 应用图标及颜色
app_icon = "octicon octicon-note"
app_color = "#3498db"

# 应用所含模块
# required_apps = ["frappe", "erpnext"]

# 每个 DocType 所属的模块映射 (Frappe 自动处理, 无需手动配置)

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/acceptance/css/acceptance.css"
# app_include_js = "/assets/acceptance/js/acceptance.js"

# include js, css files in header of web template
# web_include_css = "/assets/acceptance/css/acceptance.css"
# web_include_js = "/assets/acceptance/js/acceptance.js"

# include custom scss in every website theme (without signing in)
# website_theme_scss = "acceptance/public/scss/website"

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "acceptance/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settingsz)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#   "Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
#   "methods": "acceptance.utils.jinja_methods",
#   "filters": "acceptance.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "acceptance.install.before_install"
# after_install = "acceptance.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "acceptance.uninstall.before_uninstall"
# after_uninstall = "acceptance.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps

# before_app_include = []
# after_app_include = []

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
#   "*": {
#       "on_update": "method",
#       "on_cancel": "method",
#       "on_trash": "method"
#   }
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
#   "daily": [
#       "acceptance.tasks.check_bill_maturity"
#   ],
# }

# Testing
# -------

# before_tests = "acceptance.install.before_tests"

# Overriding Methods
# ------------------------------

# override_whitelisted_methods = {
#   "frappe.desk.doctype.event.event.get_events": "acceptance.event.get_events"
# }

# override_doctype_class = {
#   "ToDo": "custom_app.overrides.CustomToDo"
# }

# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#   "Task": "acceptance.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["acceptance.utils.before_request"]
# after_request = ["acceptance.utils.after_request"]

# Job Events
# ----------
# before_job = ["acceptance.utils.before_job"]
# after_job = ["acceptance.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
#   {
#       "doctype": "{doctype_1}",
#       "filter_by": "{filter_by}",
#       "redact_fields": ["{field_1}", "{field_2}"],
#       "partial": 1,
#   },
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#   "acceptance.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True
