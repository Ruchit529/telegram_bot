import os
import time
import asyncio
import urllib.request
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import logger

_main_event_loop = None
_global_bot = None

def register_main_loop_and_bot(bot, loop):
    global _global_bot, _main_event_loop
    _global_bot = bot
    _main_event_loop = loop
    logger.info("Bot instance and main asyncio loop registered to keep_alive server.")

WEB_EDITOR_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Edit Caption</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        :root {
            --bg-color: var(--tg-theme-bg-color, #17212b);
            --text-color: var(--tg-theme-text-color, #ffffff);
            --hint-color: var(--tg-theme-hint-color, #708499);
            --button-color: var(--tg-theme-button-color, #5288c1);
            --button-text-color: var(--tg-theme-button-text-color, #ffffff);
            --secondary-bg: var(--tg-theme-secondary-bg-color, #232e3c);
            --link-color: var(--tg-theme-link-color, #6ab2f2);
            --border-color: rgba(255, 255, 255, 0.12);
            --toolbar-bg: #1e2a38;
            --toolbar-hover: rgba(255, 255, 255, 0.08);
            --toolbar-active: rgba(82, 136, 193, 0.35);
            --danger-color: #e53935;
            --warning-color: #ffa726;
            --success-color: #4caf50;
        }
        * {
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 14px;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
            font-size: 15px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        .title {
            font-size: 17px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .char-badge {
            font-size: 12px;
            font-weight: 600;
            padding: 4px 8px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.08);
            color: var(--hint-color);
            transition: color 0.2s, background 0.2s;
        }
        .char-badge.warning {
            color: var(--warning-color);
            background: rgba(255, 167, 38, 0.15);
        }
        .char-badge.danger {
            color: var(--danger-color);
            background: rgba(229, 57, 53, 0.15);
        }

        /* Toolbar Styling */
        .toolbar {
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            background-color: var(--toolbar-bg);
            border: 1px solid var(--border-color);
            border-bottom: none;
            border-radius: 12px 12px 0 0;
            padding: 6px 8px;
            align-items: center;
        }
        .tool-btn {
            background: transparent;
            color: var(--text-color);
            border: 1px solid transparent;
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            transition: background 0.15s, border-color 0.15s;
            user-select: none;
        }
        .tool-btn:hover {
            background-color: var(--toolbar-hover);
        }
        .tool-btn.is-active {
            background-color: var(--toolbar-active);
            border-color: var(--button-color);
            color: var(--link-color);
        }
        .tool-divider {
            width: 1px;
            height: 18px;
            background: var(--border-color);
            margin: 0 3px;
        }

        /* Visual Rich Editor Area */
        .editor-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            position: relative;
            min-height: 0;
        }
        #editor {
            flex: 1;
            background-color: var(--secondary-bg);
            color: var(--text-color);
            border: 1px solid var(--border-color);
            border-radius: 0 0 12px 12px;
            padding: 14px;
            font-size: 15px;
            font-family: inherit;
            overflow-y: auto;
            outline: none;
            line-height: 1.5;
            word-break: break-word;
            white-space: pre-wrap;
        }
        #editor:focus {
            border-color: var(--button-color);
        }
        #editor:empty:before {
            content: attr(data-placeholder);
            color: var(--hint-color);
            pointer-events: none;
            display: block;
        }

        /* Formatted elements inside editor */
        #editor b, #editor strong { font-weight: 700; }
        #editor i, #editor em { font-style: italic; }
        #editor u, #editor ins { text-decoration: underline; }
        #editor s, #editor strike, #editor del { text-decoration: line-through; }
        #editor a {
            color: var(--link-color);
            text-decoration: underline;
            cursor: pointer;
        }
        #editor code {
            font-family: "SFMono-Regular", Consolas, Menlo, Monaco, monospace;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 2px 5px;
            border-radius: 5px;
            font-size: 13.5px;
            color: #e0e0e0;
        }
        #editor pre {
            font-family: "SFMono-Regular", Consolas, Menlo, Monaco, monospace;
            background: rgba(0, 0, 0, 0.35);
            border: 1px solid rgba(255, 255, 255, 0.12);
            padding: 8px 10px;
            border-radius: 8px;
            font-size: 13px;
            overflow-x: auto;
            margin: 6px 0;
            white-space: pre-wrap;
        }
        #editor blockquote {
            border-left: 3.5px solid var(--button-color);
            background: rgba(82, 136, 193, 0.12);
            padding: 6px 12px;
            margin: 6px 0;
            border-radius: 0 6px 6px 0;
            font-style: normal;
            color: rgba(255, 255, 255, 0.9);
        }
        #editor .tg-spoiler, #editor tg-spoiler {
            background: rgba(255, 255, 255, 0.15);
            border-bottom: 1px dashed rgba(255, 255, 255, 0.4);
            padding: 1px 5px;
            border-radius: 4px;
            color: #ffd54f;
            cursor: pointer;
            position: relative;
        }
        #editor .tg-spoiler:before, #editor tg-spoiler:before {
            content: "✨ ";
            font-size: 11px;
            opacity: 0.8;
        }

        /* Action Buttons */
        .btn-container {
            display: flex;
            gap: 10px;
            margin-top: 12px;
        }
        button.action-btn {
            flex: 1;
            padding: 13px;
            border: none;
            border-radius: 12px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s, transform 0.1s;
        }
        button.action-btn:active {
            transform: scale(0.98);
            opacity: 0.85;
        }
        .btn-save {
            background-color: var(--button-color);
            color: var(--button-text-color);
        }
        .btn-cancel {
            background-color: transparent;
            color: var(--hint-color);
            border: 1px solid var(--border-color);
        }

        /* Link Dialog Modal */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.65);
            backdrop-filter: blur(4px);
            display: none;
            align-items: center;
            justify-content: center;
            padding: 20px;
            z-index: 1000;
        }
        .modal-overlay.open {
            display: flex;
        }
        .modal-card {
            background: var(--secondary-bg);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 18px;
            width: 100%;
            max-width: 360px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        }
        .modal-title {
            margin: 0 0 14px 0;
            font-size: 16px;
            font-weight: 700;
        }
        .modal-input {
            width: 100%;
            padding: 10px 12px;
            background: var(--bg-color);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-color);
            font-size: 14px;
            margin-bottom: 12px;
            outline: none;
        }
        .modal-input:focus {
            border-color: var(--button-color);
        }
        .modal-actions {
            display: flex;
            gap: 8px;
            justify-content: flex-end;
            margin-top: 6px;
        }
        .modal-btn {
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            border: none;
        }
        .modal-btn-apply {
            background: var(--button-color);
            color: var(--button-text-color);
        }
        .modal-btn-cancel {
            background: transparent;
            color: var(--hint-color);
        }
        .modal-btn-remove {
            background: rgba(229, 57, 53, 0.15);
            color: var(--danger-color);
            margin-right: auto;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">✏️ Visual Caption Editor</div>
        <div id="char-counter" class="char-badge">0 / 1024</div>
    </div>

    <!-- Formatting Toolbar -->
    <div class="toolbar" id="toolbar">
        <button type="button" class="tool-btn" data-cmd="bold" title="Bold (Ctrl+B)"><b>B</b></button>
        <button type="button" class="tool-btn" data-cmd="italic" title="Italic (Ctrl+I)"><i>I</i></button>
        <button type="button" class="tool-btn" data-cmd="underline" title="Underline (Ctrl+U)"><u>U</u></button>
        <button type="button" class="tool-btn" data-cmd="strikeThrough" title="Strikethrough (Ctrl+Shift+X)"><s>S</s></button>
        <div class="tool-divider"></div>
        <button type="button" class="tool-btn" data-cmd="spoiler" title="Spoiler">✨ Spoiler</button>
        <button type="button" class="tool-btn" data-cmd="code" title="Monospace">&lt;/&gt;</button>
        <button type="button" class="tool-btn" data-cmd="link" title="Link (Ctrl+K)">🔗 Link</button>
        <button type="button" class="tool-btn" data-cmd="quote" title="Quote">❝ Quote</button>
        <div class="tool-divider"></div>
        <button type="button" class="tool-btn" data-cmd="clear" title="Clear Formatting">🧹</button>
    </div>

    <!-- Contenteditable Visual Editor -->
    <div class="editor-container">
        <div id="editor" contenteditable="true" spellcheck="true" data-placeholder="Type or paste your formatted caption here..."></div>
    </div>

    <!-- Bottom Actions -->
    <div class="btn-container">
        <button class="action-btn btn-cancel" id="cancel-btn">❌ Cancel</button>
        <button class="action-btn btn-save" id="save-btn">💾 Save & Apply</button>
    </div>

    <!-- Link Modal -->
    <div class="modal-overlay" id="link-modal">
        <div class="modal-card">
            <h4 class="modal-title">🔗 Insert / Edit Link</h4>
            <input type="text" id="link-text" class="modal-input" placeholder="Display text">
            <input type="url" id="link-url" class="modal-input" placeholder="https://example.com" value="https://">
            <div class="modal-actions">
                <button type="button" class="modal-btn modal-btn-remove" id="modal-remove-link" style="display:none;">Remove</button>
                <button type="button" class="modal-btn modal-btn-cancel" id="modal-cancel-link">Cancel</button>
                <button type="button" class="modal-btn modal-btn-apply" id="modal-apply-link">Apply</button>
            </div>
        </div>
    </div>

    <script>
        const tg = window.Telegram?.WebApp;
        if (tg) {
            tg.expand();
            tg.ready();
        }

        const editor = document.getElementById('editor');
        const charCounter = document.getElementById('char-counter');
        const toolbar = document.getElementById('toolbar');
        const linkModal = document.getElementById('link-modal');
        const linkTextInput = document.getElementById('link-text');
        const linkUrlInput = document.getElementById('link-url');
        const modalRemoveLink = document.getElementById('modal-remove-link');
        const modalCancelLink = document.getElementById('modal-cancel-link');
        const modalApplyLink = document.getElementById('modal-apply-link');

        let savedSelectionRange = null;
        let currentLinkNode = null;

        // Convert Telegram HTML to visually rendered Editor HTML
        function loadTelegramHtml(rawHtml) {
            if (!rawHtml) return "";
            let html = rawHtml;
            // Convert <tg-spoiler> tags to visual span
            html = html.replace(/<tg-spoiler>(.*?)<\/tg-spoiler>/gi, '<span class="tg-spoiler">$1</span>');
            // Convert newlines to <br> if not inside HTML tags
            html = html.replace(/\r?\n/g, '<br>');
            return html;
        }

        // Initialize editor content from URL parameter
        const urlParams = new URLSearchParams(window.location.search);
        const textParam = urlParams.get('text');
        if (textParam !== null) {
            const decoded = decodeURIComponent(textParam);
            editor.innerHTML = loadTelegramHtml(decoded);
        }

        // Convert DOM tree back into clean Telegram-compliant HTML
        function serializeToTelegramHtml(node) {
            if (!node) return "";
            
            if (node.nodeType === Node.TEXT_NODE) {
                return node.textContent
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');
            }

            if (node.nodeType !== Node.ELEMENT_NODE) {
                return "";
            }

            const tag = node.tagName.toLowerCase();
            let inner = "";
            for (const child of node.childNodes) {
                inner += serializeToTelegramHtml(child);
            }

            switch (tag) {
                case 'b':
                case 'strong':
                    return inner.trim() ? `<b>${inner}</b>` : "";
                case 'i':
                case 'em':
                    return inner.trim() ? `<i>${inner}</i>` : "";
                case 'u':
                case 'ins':
                    return inner.trim() ? `<u>${inner}</u>` : "";
                case 's':
                case 'strike':
                case 'del':
                    return inner.trim() ? `<s>${inner}</s>` : "";
                case 'code':
                    return inner ? `<code>${inner}</code>` : "";
                case 'pre':
                    return inner ? `<pre>${inner}</pre>` : "";
                case 'blockquote':
                    return inner ? `<blockquote>${inner}</blockquote>` : "";
                case 'span':
                    if (node.classList.contains('tg-spoiler') || node.getAttribute('class') === 'tg-spoiler') {
                        return inner.trim() ? `<tg-spoiler>${inner}</tg-spoiler>` : "";
                    }
                    return inner;
                case 'tg-spoiler':
                    return inner.trim() ? `<tg-spoiler>${inner}</tg-spoiler>` : "";
                case 'a':
                    const href = node.getAttribute('href');
                    if (href && inner.trim()) {
                        const safeHref = href.replace(/"/g, '&quot;');
                        return `<a href="${safeHref}">${inner}</a>`;
                    }
                    return inner;
                case 'br':
                    return '\n';
                case 'p':
                case 'div':
                    return inner ? `${inner}\n` : '\n';
                default:
                    return inner;
            }
        }

        function getFinalTelegramHtml() {
            let result = serializeToTelegramHtml(editor);
            // Normalize trailing newlines
            result = result.replace(/\n+$/, '');
            return result;
        }

        // Live Character Counter update
        function updateCharCount() {
            const finalHtml = getFinalTelegramHtml();
            const len = finalHtml.length;
            charCounter.textContent = `${len} / 1024`;
            
            charCounter.classList.remove('warning', 'danger');
            if (len > 1024) {
                charCounter.classList.add('danger');
            } else if (len > 900) {
                charCounter.classList.add('warning');
            }
        }

        editor.addEventListener('input', updateCharCount);
        updateCharCount();

        // Update toolbar active states
        function updateToolbarState() {
            const commands = ['bold', 'italic', 'underline', 'strikeThrough'];
            commands.forEach(cmd => {
                const btn = toolbar.querySelector(`[data-cmd="${cmd}"]`);
                if (btn) {
                    if (document.queryCommandState(cmd)) {
                        btn.classList.add('is-active');
                    } else {
                        btn.classList.remove('is-active');
                    }
                }
            });

            // Check code, spoiler, link, quote
            const selection = window.getSelection();
            if (!selection || !selection.anchorNode) return;
            
            let parent = selection.anchorNode;
            if (parent.nodeType === Node.TEXT_NODE) parent = parent.parentNode;

            const isCode = !!parent.closest('code, pre');
            const isSpoiler = !!parent.closest('.tg-spoiler, tg-spoiler');
            const isLink = !!parent.closest('a');
            const isQuote = !!parent.closest('blockquote');

            toolbar.querySelector('[data-cmd="code"]')?.classList.toggle('is-active', isCode);
            toolbar.querySelector('[data-cmd="spoiler"]')?.classList.toggle('is-active', isSpoiler);
            toolbar.querySelector('[data-cmd="link"]')?.classList.toggle('is-active', isLink);
            toolbar.querySelector('[data-cmd="quote"]')?.classList.toggle('is-active', isQuote);
        }

        document.addEventListener('selectionchange', () => {
            if (document.activeElement === editor || editor.contains(document.activeElement)) {
                updateToolbarState();
            }
        });

        // Save & restore selection ranges for modals
        function saveSelection() {
            const sel = window.getSelection();
            if (sel.rangeCount > 0) {
                savedSelectionRange = sel.getRangeAt(0).cloneRange();
            }
        }

        function restoreSelection() {
            if (savedSelectionRange) {
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(savedSelectionRange);
            }
        }

        // Wrap or unwrap custom tags (spoiler, code, blockquote)
        function toggleWrapTag(tagName, className = '') {
            editor.focus();
            const selection = window.getSelection();
            if (!selection || selection.rangeCount === 0) return;

            const range = selection.getRangeAt(0);
            let parent = selection.anchorNode;
            if (parent.nodeType === Node.TEXT_NODE) parent = parent.parentNode;

            const existingWrapper = className 
                ? parent.closest(`.${className}`) 
                : parent.closest(tagName);

            if (existingWrapper && editor.contains(existingWrapper)) {
                // Unwrap
                const parentNode = existingWrapper.parentNode;
                while (existingWrapper.firstChild) {
                    parentNode.insertBefore(existingWrapper.firstChild, existingWrapper);
                }
                parentNode.removeChild(existingWrapper);
            } else {
                // Wrap
                if (range.collapsed) return;
                const wrapper = document.createElement(tagName);
                if (className) wrapper.className = className;
                try {
                    wrapper.appendChild(range.extractContents());
                    range.insertNode(wrapper);
                    selection.selectAllChildren(wrapper);
                } catch(e) {}
            }
            updateCharCount();
            updateToolbarState();
        }

        // Toolbar Button Click Handler
        toolbar.addEventListener('click', (e) => {
            const btn = e.target.closest('.tool-btn');
            if (!btn) return;
            e.preventDefault();

            const cmd = btn.getAttribute('data-cmd');
            if (!cmd) return;

            if (cmd === 'bold' || cmd === 'italic' || cmd === 'underline' || cmd === 'strikeThrough') {
                document.execCommand(cmd, false, null);
                updateCharCount();
                updateToolbarState();
            } else if (cmd === 'code') {
                toggleWrapTag('code');
            } else if (cmd === 'spoiler') {
                toggleWrapTag('span', 'tg-spoiler');
            } else if (cmd === 'quote') {
                toggleWrapTag('blockquote');
            } else if (cmd === 'link') {
                openLinkModal();
            } else if (cmd === 'clear') {
                document.execCommand('removeFormat', false, null);
                document.execCommand('unlink', false, null);
                // Clean any wrapping spans/code/quote
                const sel = window.getSelection();
                if (sel && sel.anchorNode) {
                    let p = sel.anchorNode;
                    if (p.nodeType === Node.TEXT_NODE) p = p.parentNode;
                    const wrap = p.closest('code, blockquote, .tg-spoiler, tg-spoiler');
                    if (wrap && editor.contains(wrap)) {
                        const parentNode = wrap.parentNode;
                        while (wrap.firstChild) {
                            parentNode.insertBefore(wrap.firstChild, wrap);
                        }
                        parentNode.removeChild(wrap);
                    }
                }
                updateCharCount();
                updateToolbarState();
            }
        });

        // Link Modal Handlers
        function openLinkModal() {
            saveSelection();
            const sel = window.getSelection();
            currentLinkNode = null;

            let selectedText = "";
            let linkHref = "https://";

            if (sel && sel.anchorNode) {
                let parent = sel.anchorNode;
                if (parent.nodeType === Node.TEXT_NODE) parent = parent.parentNode;
                const existingA = parent.closest('a');
                if (existingA && editor.contains(existingA)) {
                    currentLinkNode = existingA;
                    selectedText = existingA.textContent;
                    linkHref = existingA.getAttribute('href') || 'https://';
                    modalRemoveLink.style.display = 'block';
                } else {
                    selectedText = sel.toString();
                    modalRemoveLink.style.display = 'none';
                }
            }

            linkTextInput.value = selectedText;
            linkUrlInput.value = linkHref;
            linkModal.classList.add('open');
            linkUrlInput.focus();
        }

        function closeLinkModal() {
            linkModal.classList.remove('open');
            currentLinkNode = null;
            editor.focus();
            restoreSelection();
        }

        modalCancelLink.addEventListener('click', closeLinkModal);

        modalRemoveLink.addEventListener('click', () => {
            if (currentLinkNode && editor.contains(currentLinkNode)) {
                const parent = currentLinkNode.parentNode;
                while (currentLinkNode.firstChild) {
                    parent.insertBefore(currentLinkNode.firstChild, currentLinkNode);
                }
                parent.removeChild(currentLinkNode);
            }
            closeLinkModal();
            updateCharCount();
            updateToolbarState();
        });

        modalApplyLink.addEventListener('click', () => {
            let url = linkUrlInput.value.trim();
            const text = linkTextInput.value.trim() || url;
            
            if (!url) {
                closeLinkModal();
                return;
            }

            if (!url.startsWith('http://') && !url.startsWith('https://') && !url.startsWith('tg://')) {
                url = 'https://' + url;
            }

            restoreSelection();

            if (currentLinkNode && editor.contains(currentLinkNode)) {
                currentLinkNode.setAttribute('href', url);
                currentLinkNode.textContent = text;
            } else {
                const sel = window.getSelection();
                if (sel && sel.rangeCount > 0 && !sel.getRangeAt(0).collapsed) {
                    const range = sel.getRangeAt(0);
                    const a = document.createElement('a');
                    a.href = url;
                    a.appendChild(range.extractContents());
                    range.insertNode(a);
                } else {
                    const a = document.createElement('a');
                    a.href = url;
                    a.textContent = text;
                    if (savedSelectionRange) {
                        savedSelectionRange.insertNode(a);
                    } else {
                        editor.appendChild(a);
                    }
                }
            }

            closeLinkModal();
            updateCharCount();
            updateToolbarState();
        });

        // Rich Paste Interceptor (Preserves styles, abstracts raw tags)
        editor.addEventListener('paste', (e) => {
            const clipboard = e.clipboardData;
            if (!clipboard) return;

            const html = clipboard.getData('text/html');
            if (html) {
                e.preventDefault();
                
                const parser = new DOMParser();
                const doc = parser.parseFromString(html, 'text/html');

                // Sanitize and transform DOM tree into clean Telegram tags
                function cleanNode(node) {
                    if (node.nodeType === Node.TEXT_NODE) {
                        return document.createTextNode(node.textContent);
                    }
                    if (node.nodeType !== Node.ELEMENT_NODE) {
                        return null;
                    }

                    const tag = node.tagName.toLowerCase();
                    const style = node.style || {};
                    const isBold = style.fontWeight === 'bold' || parseInt(style.fontWeight, 10) >= 600 || tag === 'b' || tag === 'strong' || tag.startsWith('h');
                    const isItalic = style.fontStyle === 'italic' || tag === 'i' || tag === 'em';
                    const isUnderline = (style.textDecoration && style.textDecoration.includes('underline')) || tag === 'u' || tag === 'ins';
                    const isStrike = (style.textDecoration && style.textDecoration.includes('line-through')) || tag === 's' || tag === 'strike' || tag === 'del';
                    const isCode = style.fontFamily?.includes('monospace') || tag === 'code' || tag === 'pre';
                    const isSpoiler = node.classList.contains('tg-spoiler') || tag === 'tg-spoiler';

                    const fragment = document.createDocumentFragment();
                    for (const child of node.childNodes) {
                        const cleanedChild = cleanNode(child);
                        if (cleanedChild) fragment.appendChild(cleanedChild);
                    }

                    let wrapper = fragment;

                    if (tag === 'a' && node.getAttribute('href')) {
                        const a = document.createElement('a');
                        a.href = node.getAttribute('href');
                        a.appendChild(wrapper);
                        wrapper = a;
                    } else if (tag === 'blockquote') {
                        const bq = document.createElement('blockquote');
                        bq.appendChild(wrapper);
                        wrapper = bq;
                    }

                    if (isSpoiler) {
                        const sp = document.createElement('span');
                        sp.className = 'tg-spoiler';
                        sp.appendChild(wrapper);
                        wrapper = sp;
                    }
                    if (isCode) {
                        const cd = document.createElement('code');
                        cd.appendChild(wrapper);
                        wrapper = cd;
                    }
                    if (isStrike) {
                        const s = document.createElement('s');
                        s.appendChild(wrapper);
                        wrapper = s;
                    }
                    if (isUnderline) {
                        const u = document.createElement('u');
                        u.appendChild(wrapper);
                        wrapper = u;
                    }
                    if (isItalic) {
                        const i = document.createElement('i');
                        i.appendChild(wrapper);
                        wrapper = i;
                    }
                    if (isBold) {
                        const b = document.createElement('b');
                        b.appendChild(wrapper);
                        wrapper = b;
                    }

                    if (tag === 'p' || tag === 'div' || tag === 'li') {
                        const block = document.createElement('div');
                        if (tag === 'li') block.textContent = '• ';
                        block.appendChild(wrapper);
                        return block;
                    }
                    if (tag === 'br') {
                        return document.createElement('br');
                    }

                    return wrapper;
                }

                const cleanedFragment = cleanNode(doc.body);
                if (cleanedFragment) {
                    const tempDiv = document.createElement('div');
                    tempDiv.appendChild(cleanedFragment);
                    document.execCommand('insertHTML', false, tempDiv.innerHTML);
                }
                updateCharCount();
                updateToolbarState();
            }
        });

        // Keyboard Shortcuts
        document.addEventListener('keydown', (e) => {
            const isCtrl = e.ctrlKey || e.metaKey;
            if (isCtrl && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                openLinkModal();
            }
        });

        // Save & Apply Action
        document.getElementById('save-btn').onclick = function() {
            const finalTelegramHtml = getFinalTelegramHtml();
            const userId = tg?.initDataUnsafe?.user?.id || urlParams.get('user_id');

            const saveBtn = document.getElementById('save-btn');
            saveBtn.innerText = "⏳ Saving...";
            saveBtn.disabled = true;

            fetch('/api/save_caption', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: parseInt(userId), text: finalTelegramHtml })
            })
            .then(res => res.json())
            .then(data => {
                try { tg?.sendData(JSON.stringify({ action: "update_caption", text: finalTelegramHtml })); } catch(e) {}
                setTimeout(() => { if (tg) tg.close(); }, 150);
            })
            .catch(err => {
                try { tg?.sendData(JSON.stringify({ action: "update_caption", text: finalTelegramHtml })); } catch(e) {}
                setTimeout(() => { if (tg) tg.close(); }, 150);
            });
        };

        // Cancel Action
        document.getElementById('cancel-btn').onclick = function() {
            if (tg) tg.close();
        };
    </script>
</body>
</html>
"""

async def _apply_caption_update(user_id: int, text: str):
    """Bridge routine to update FSM draft state and edit preview message on main asyncio loop."""
    try:
        from services.fsm import fsm, States
        from handlers.post_workflow import _update_existing_preview
        from handlers.error_handler import safe_delete_message

        state, draft = await fsm.get_state(user_id)
        if draft:
            guide_id = draft.get("caption_guide_msg_id")
            if guide_id and _global_bot:
                await safe_delete_message(_global_bot, user_id, guide_id)
                if "caption_guide_msg_id" in draft:
                    del draft["caption_guide_msg_id"]

            draft["translated_text"] = text
            draft["was_translated"] = False

            await fsm.set_state(user_id, States.PREVIEW_GENERATED, draft)
            if _global_bot:
                await _update_existing_preview(_global_bot, user_id, draft)
    except Exception as e:
        logger.error(f"Error applying caption update: {e}", exc_info=True)

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/', '/ping'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "alive", "message": "Antigravity Bot is active!"}')
        elif self.path.startswith('/editor') or self.path.startswith('/webapp'):
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(WEB_EDITOR_HTML.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/save_caption':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                import json
                data = json.loads(post_data.decode('utf-8'))
                user_id = data.get("user_id")
                text = data.get("text", "")
                
                if user_id and _main_event_loop and _main_event_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        _apply_caption_update(int(user_id), text),
                        _main_event_loop
                    )

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            except Exception as e:
                logger.error(f"Error in /api/save_caption POST: {e}", exc_info=True)
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    # Suppress standard request logging to avoid log pollution
    def log_message(self, format, *args):
        logger.debug(format % args)

def run_http_server(port: int):
    try:
        server = HTTPServer(('0.0.0.0', port), KeepAliveHandler)
        logger.info(f"Keep-alive HTTP server listening on 0.0.0.0:{port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start keep-alive HTTP server: {e}", exc_info=True)

async def self_ping_loop():
    # Render automatically populates RENDER_EXTERNAL_URL (e.g., https://bot-service.onrender.com)
    ping_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PING_URL")
    if not ping_url:
        logger.warning("Neither RENDER_EXTERNAL_URL nor PING_URL is set in environment. Self-pinging is disabled.")
        return

    if not ping_url.startswith(("http://", "https://")):
        ping_url = "https://" + ping_url
    
    ping_url = ping_url.rstrip("/") + "/ping"
    logger.info(f"Self-pinging keep-alive loop initialized. Target URL: {ping_url}")

    # Wait 60 seconds after startup before sending the first self-ping
    await asyncio.sleep(60)

    while True:
        try:
            def ping():
                try:
                    req = urllib.request.Request(
                        ping_url,
                        headers={'User-Agent': 'Antigravity-Keep-Alive/1.0'}
                    )
                    with urllib.request.urlopen(req, timeout=15) as response:
                        return response.read().decode('utf-8')
                except Exception as ex:
                    return f"HTTP Request Error: {str(ex)}"

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, ping)
            logger.info(f"Keep-alive ping sent successfully. Response: {result}")
        except Exception as e:
            logger.error(f"Keep-alive self-ping failed: {e}")

        # Ping every 10 minutes (600 seconds) to prevent Render's 15-minute sleep timeout
        await asyncio.sleep(600)

def start_keep_alive():
    """Starts the port listener and schedules the self-ping loop."""
    port_str = os.getenv("PORT", "10000")
    try:
        port = int(port_str)
    except ValueError:
        logger.warning(f"Invalid PORT value: '{port_str}'. Defaulting to 10000.")
        port = 10000

    # Run the HTTP server in a separate background daemon thread to avoid blocking the asyncio event loop
    threading.Thread(target=run_http_server, args=(port,), daemon=True).start()

    # Schedule the self-ping loop on the running asyncio event loop
    asyncio.create_task(self_ping_loop())
