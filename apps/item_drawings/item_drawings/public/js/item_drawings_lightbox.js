// item_drawings —— 物料图纸 Lightbox
//
// 作用：在 ERPNext 里所有 Item Link 字段的跳转链接前加一个 eye icon，
// 点击后弹出 carousel lightbox 展示该 Item 的所有 active 图纸
// （custom_drawings 子表里 disabled = 0 的条目），is_main 的排在首位。
//
// - 图片：居中预览，顶部工具栏支持旋转 / 放大 / 缩小 / 下载 / 关闭，
//   左右箭头切上一张/下一张，键盘 ←→ Esc 同理。
// - 非图片（PDF/DWG 等）：中间显示通用文件 SVG 图标 + 文件名，
//   顶部工具栏只保留下载 / 关闭（旋转/缩放按钮隐藏）。
//
// 零外部依赖：jQuery + 内联 SVG + 动态注入 <style>。

(function () {
    const EYE_CLASS = "idw-drawings-eye";
    const OVERLAY_CLASS = "idw-drawings-lightbox";
    const IMG_EXT_RE = /\.(png|jpe?g|gif|webp|svg|bmp|tiff?)$/i;

    // ---------- Eye icon 注入 ----------
    // v16 的 formatters.js Link 分支用 `a.innerText = label` 渲染，link_formatters
    // 的返回值会被当成纯文本（HTML 会被转义），所以 eye icon 不能走 link_formatters。
    // 改为用 MutationObserver 监听所有 `a[data-doctype="Item"]`，在 <a> 的前面
    // 插入一个独立的 <span> 兄弟节点作为 eye icon —— 天然覆盖 form / list / grid /
    // report 里所有 Item Link 字段，而且不依赖任何特定渲染路径。
    const EYE_SVG =
        '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" ' +
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
        'stroke-linejoin="round">' +
        '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>' +
        '<circle cx="12" cy="12" r="3"/></svg>';
    const PROCESSED_ATTR = "data-idw-processed";

    function item_code_of(anchor) {
        return (
            anchor.getAttribute("data-name") ||
            anchor.getAttribute("data-value") ||
            (anchor.textContent || "").trim()
        );
    }

    function inject_eye(anchor) {
        if (!anchor || anchor.getAttribute(PROCESSED_ATTR)) return;
        if (anchor.getAttribute("data-doctype") !== "Item") return;
        const item_code = item_code_of(anchor);
        if (!item_code) return;
        anchor.setAttribute(PROCESSED_ATTR, "1");
        const span = document.createElement("span");
        span.className = EYE_CLASS;
        span.setAttribute("data-item", item_code);
        span.setAttribute("title", __("View drawings"));
        span.innerHTML = EYE_SVG;
        anchor.parentNode.insertBefore(span, anchor);
    }

    function scan(root) {
        const anchors = (root || document).querySelectorAll(
            'a[data-doctype="Item"]:not([' + PROCESSED_ATTR + '])'
        );
        anchors.forEach(inject_eye);
    }

    function start_observer() {
        scan(document);
        const observer = new MutationObserver((mutations) => {
            for (const m of mutations) {
                for (const node of m.addedNodes) {
                    if (node.nodeType !== 1) continue;
                    if (
                        node.tagName === "A" &&
                        node.getAttribute("data-doctype") === "Item"
                    ) {
                        inject_eye(node);
                    } else if (node.querySelectorAll) {
                        scan(node);
                    }
                }
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start_observer);
    } else {
        start_observer();
    }

    // ---------- Click delegation（capture 阶段）----------
    // 用 capture 阶段 + stopImmediatePropagation，在 list row / grid cell 等
    // 祖先元素的 bubble click handler 触发跳转之前拦截掉。
    // 同时拦 mousedown，避免 Frappe 某些控件在 mousedown 阶段就开始导航。
    function handle_eye(e) {
        const span = e.target.closest && e.target.closest("." + EYE_CLASS);
        if (!span) return;
        e.preventDefault();
        e.stopPropagation();
        if (e.stopImmediatePropagation) e.stopImmediatePropagation();
        if (e.type !== "click") return;
        const item_code = span.getAttribute("data-item");
        if (item_code) open_lightbox(item_code);
    }
    document.addEventListener("mousedown", handle_eye, true);
    document.addEventListener("click", handle_eye, true);

    function open_lightbox(item_code) {
        frappe.db
            .get_doc("Item", item_code)
            .then((item) => {
                const drawings = (item.custom_drawings || [])
                    .filter((d) => d.drawing_file && !d.disabled)
                    .sort((a, b) => (b.is_main || 0) - (a.is_main || 0));
                if (!drawings.length) {
                    frappe.show_alert({
                        message: __("No active drawings for {0}", [item_code]),
                        indicator: "orange",
                    });
                    return;
                }
                new DrawingsLightbox(item, drawings).open();
            })
            .catch(() => {
                frappe.show_alert({
                    message: __("Failed to load {0}", [item_code]),
                    indicator: "red",
                });
            });
    }

    // ---------- Lightbox 组件 ----------
    class DrawingsLightbox {
        constructor(item, drawings) {
            this.item = item;
            this.drawings = drawings;
            this.index = 0;
            this.rotation = 0;
            this.zoom = 1;
            this.$overlay = null;
            this._kb_handler = null;
        }

        open() {
            inject_styles_once();
            this.$overlay = $(this._template()).appendTo("body");
            this._bind_events();
            this._render();
            this.$overlay.trigger("focus");
        }

        _template() {
            const t = (key) => frappe.utils.escape_html(__(key));
            return (
                '<div class="' +
                OVERLAY_CLASS +
                '" tabindex="-1">' +
                '  <div class="idw-lb-topbar">' +
                '    <div class="idw-lb-caption"></div>' +
                '    <div class="idw-lb-tools">' +
                '      <button type="button" class="idw-lb-btn idw-lb-rotate" title="' +
                t("Rotate") +
                '">' +
                icon_svg("rotate") +
                "</button>" +
                '      <button type="button" class="idw-lb-btn idw-lb-zoom-out" title="' +
                t("Zoom out") +
                '">' +
                icon_svg("zoom-out") +
                "</button>" +
                '      <button type="button" class="idw-lb-btn idw-lb-zoom-in" title="' +
                t("Zoom in") +
                '">' +
                icon_svg("zoom-in") +
                "</button>" +
                '      <button type="button" class="idw-lb-btn idw-lb-download" title="' +
                t("Download") +
                '">' +
                icon_svg("download") +
                "</button>" +
                '      <button type="button" class="idw-lb-btn idw-lb-close" title="' +
                t("Close") +
                '">' +
                icon_svg("close") +
                "</button>" +
                "    </div>" +
                "  </div>" +
                '  <button type="button" class="idw-lb-nav idw-lb-prev" title="' +
                t("Previous") +
                '">' +
                icon_svg("chevron-left") +
                "</button>" +
                '  <button type="button" class="idw-lb-nav idw-lb-next" title="' +
                t("Next") +
                '">' +
                icon_svg("chevron-right") +
                "</button>" +
                '  <div class="idw-lb-stage"></div>' +
                '  <div class="idw-lb-footer"></div>' +
                "</div>"
            );
        }

        _bind_events() {
            const self = this;
            this.$overlay.find(".idw-lb-close").on("click", () => self.close());
            this.$overlay
                .find(".idw-lb-prev")
                .on("click", () => self.goto(self.index - 1));
            this.$overlay
                .find(".idw-lb-next")
                .on("click", () => self.goto(self.index + 1));
            this.$overlay.find(".idw-lb-rotate").on("click", () => self.rotate());
            this.$overlay
                .find(".idw-lb-zoom-in")
                .on("click", () => self.zoom_by(1.25));
            this.$overlay
                .find(".idw-lb-zoom-out")
                .on("click", () => self.zoom_by(0.8));
            this.$overlay.find(".idw-lb-download").on("click", () => self.download());
            // 点击遮罩空白关闭
            this.$overlay.on("click", (e) => {
                if (e.target === self.$overlay[0]) self.close();
            });
            this._kb_handler = (e) => {
                if (e.key === "Escape") self.close();
                else if (e.key === "ArrowLeft") self.goto(self.index - 1);
                else if (e.key === "ArrowRight") self.goto(self.index + 1);
            };
            $(document).on("keydown.idw-lb", this._kb_handler);
        }

        current() {
            return this.drawings[this.index];
        }

        goto(new_index) {
            const n = this.drawings.length;
            if (n === 0) return;
            new_index = ((new_index % n) + n) % n;
            if (new_index === this.index) return;
            this.index = new_index;
            this.rotation = 0;
            this.zoom = 1;
            this._render();
        }

        rotate() {
            this.rotation = (this.rotation + 90) % 360;
            this._apply_transform();
        }

        zoom_by(factor) {
            this.zoom = Math.max(0.1, Math.min(10, this.zoom * factor));
            this._apply_transform();
        }

        _apply_transform() {
            const $img = this.$overlay.find(".idw-lb-stage img");
            if ($img.length) {
                $img.css(
                    "transform",
                    "rotate(" + this.rotation + "deg) scale(" + this.zoom + ")"
                );
            }
        }

        download() {
            const d = this.current();
            if (!d || !d.drawing_file) return;
            const a = document.createElement("a");
            a.href = d.drawing_file;
            a.download = d.drawing_name || "";
            a.target = "_blank";
            a.rel = "noopener";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }

        _render() {
            const d = this.current();
            const is_image = IMG_EXT_RE.test(d.drawing_file || "");
            const $stage = this.$overlay.find(".idw-lb-stage").empty();
            if (is_image) {
                $stage.append(
                    '<img src="' +
                        frappe.utils.escape_html(d.drawing_file) +
                        '" alt="' +
                        frappe.utils.escape_html(d.drawing_name || "") +
                        '">'
                );
                this.$overlay
                    .find(".idw-lb-rotate, .idw-lb-zoom-in, .idw-lb-zoom-out")
                    .css("display", "");
                this._apply_transform();
            } else {
                const filename = (d.drawing_file || "").split("/").pop();
                $stage.append(
                    '<div class="idw-lb-fileview">' +
                        '<svg width="120" height="120" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
                        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
                        '<polyline points="14 2 14 8 20 8"/>' +
                        "</svg>" +
                        '<div class="idw-lb-filename">' +
                        frappe.utils.escape_html(filename) +
                        "</div>" +
                        "</div>"
                );
                // 非图片：隐藏旋转/缩放按钮
                this.$overlay
                    .find(".idw-lb-rotate, .idw-lb-zoom-in, .idw-lb-zoom-out")
                    .css("display", "none");
            }
            const parts = [
                "<strong>" + frappe.utils.escape_html(this.item.item_code) + "</strong>",
            ];
            if (d.drawing_name) parts.push(frappe.utils.escape_html(d.drawing_name));
            if (d.is_main)
                parts.push(
                    '<span class="idw-lb-main">' + frappe.utils.escape_html(__("Main")) + "</span>"
                );
            if (d.version) parts.push("v" + frappe.utils.escape_html(d.version));
            if (d.remark)
                parts.push(
                    '<span class="idw-lb-muted">' +
                        frappe.utils.escape_html(d.remark) +
                        "</span>"
                );
            this.$overlay.find(".idw-lb-caption").html(parts.join(" · "));
            this.$overlay
                .find(".idw-lb-footer")
                .text(this.index + 1 + " / " + this.drawings.length);
            const hide_nav = this.drawings.length <= 1;
            this.$overlay
                .find(".idw-lb-prev, .idw-lb-next")
                .css("display", hide_nav ? "none" : "");
        }

        close() {
            if (this._kb_handler) $(document).off("keydown.idw-lb");
            if (this.$overlay) this.$overlay.remove();
        }
    }

    // ---------- SVG icons ----------
    function icon_svg(name) {
        const attrs =
            'width="18" height="18" viewBox="0 0 24 24" fill="none" ' +
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
        switch (name) {
            case "rotate":
                return (
                    "<svg " +
                    attrs +
                    '><path d="M23 4v6h-6"/><path d="M20.49 15A9 9 0 1 1 18 5.61L23 10"/></svg>'
                );
            case "zoom-in":
                return (
                    "<svg " +
                    attrs +
                    '><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>'
                );
            case "zoom-out":
                return (
                    "<svg " +
                    attrs +
                    '><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/></svg>'
                );
            case "download":
                return (
                    "<svg " +
                    attrs +
                    '><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>'
                );
            case "close":
                return (
                    "<svg " +
                    attrs +
                    '><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'
                );
            case "chevron-left":
                return (
                    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>'
                );
            case "chevron-right":
                return (
                    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>'
                );
        }
        return "";
    }

    // ---------- Styles ----------
    let _styles_injected = false;
    function inject_styles_once() {
        if (_styles_injected) return;
        _styles_injected = true;
        const css =
            "." + EYE_CLASS + " { display:inline-block; vertical-align:-0.15em; line-height:1; font-size:1em; width:1em; height:1em; cursor:pointer; color:var(--text-muted, #6c7680); margin-right:6px; }" +
            "." + EYE_CLASS + " > svg { display:block; width:1em; height:1em; }" +
            "." + EYE_CLASS + ":hover { color: var(--primary-color, #5e64ff); }" +
            "." + OVERLAY_CLASS + " { position:fixed; inset:0; background:rgba(0,0,0,0.88); z-index:9999; display:flex; align-items:center; justify-content:center; outline:none; }" +
            "." + OVERLAY_CLASS + " .idw-lb-topbar { position:absolute; top:0; left:0; right:0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center; color:#fff; background:linear-gradient(rgba(0,0,0,0.65), transparent); pointer-events:none; }" +
            "." + OVERLAY_CLASS + " .idw-lb-caption { font-size:14px; pointer-events:auto; }" +
            "." + OVERLAY_CLASS + " .idw-lb-muted { color:#bbb; font-weight:400; }" +
            "." + OVERLAY_CLASS + " .idw-lb-main { background:#f0ad4e; color:#000; padding:1px 6px; border-radius:3px; font-size:11px; font-weight:600; }" +
            "." + OVERLAY_CLASS + " .idw-lb-tools { display:flex; gap:8px; pointer-events:auto; }" +
            "." + OVERLAY_CLASS + " .idw-lb-btn { background:rgba(255,255,255,0.12); border:none; color:#fff; width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; cursor:pointer; transition:background 0.15s; }" +
            "." + OVERLAY_CLASS + " .idw-lb-btn:hover { background:rgba(255,255,255,0.28); }" +
            "." + OVERLAY_CLASS + " .idw-lb-nav { position:absolute; top:50%; transform:translateY(-50%); background:rgba(255,255,255,0.12); border:none; color:#fff; width:48px; height:48px; border-radius:50%; display:flex; align-items:center; justify-content:center; cursor:pointer; }" +
            "." + OVERLAY_CLASS + " .idw-lb-nav:hover { background:rgba(255,255,255,0.28); }" +
            "." + OVERLAY_CLASS + " .idw-lb-prev { left:20px; }" +
            "." + OVERLAY_CLASS + " .idw-lb-next { right:20px; }" +
            "." + OVERLAY_CLASS + " .idw-lb-stage { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; overflow:visible; pointer-events:none; }" +
            "." + OVERLAY_CLASS + " .idw-lb-stage > * { pointer-events:auto; }" +
            "." + OVERLAY_CLASS + " .idw-lb-stage img { max-width:90vw; max-height:82vh; object-fit:contain; transition:transform 0.2s ease; user-select:none; -webkit-user-drag:none; }" +
            "." + OVERLAY_CLASS + " .idw-lb-fileview { color:#fff; text-align:center; display:flex; flex-direction:column; align-items:center; gap:16px; }" +
            "." + OVERLAY_CLASS + " .idw-lb-filename { font-size:14px; color:#ccc; word-break:break-all; max-width:480px; }" +
            "." + OVERLAY_CLASS + " .idw-lb-footer { position:absolute; bottom:16px; left:0; right:0; text-align:center; color:#ccc; font-size:12px; }";
        const $s = $("<style>").prop("type", "text/css").html(css);
        $("head").append($s);
    }
})();
