/**
 * Course-scoped chatbot UI with chat rooms and history sidebar.
 *
 * @module     local_chatbot/popup
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

import Ajax from "core/ajax";
import Notification from "core/notification";

const formatReplyDisplay = (text) => {
    if (!text) {
        return "";
    }
    return text
        .replace(/\*\*([^*]+)\*\*/g, "$1")
        .replace(/\*([^*]+)\*/g, "$1")
        .replace(/\*\*/g, " ")
        .replace(/^#{1,6}\s+/gm, "")
        .trim();
};

const escapeHtml = (s) =>
    String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");

/**
 * Bot reply: plain cleanup + clickable Markdown links [label](http...).
 *
 * @param {string} text
 * @returns {string}
 */
const formatBotReplyHtml = (text) => {
    if (!text) {
        return "";
    }
    const plainFirst = formatReplyDisplay(text);
    const re = /\[([^\]]*)\]\((https?:\/\/[^)\s]+)\)/g;
    const parts = [];
    let pos = 0;
    let m;
    while ((m = re.exec(plainFirst)) !== null) {
        if (m.index > pos) {
            parts.push(escapeHtml(plainFirst.slice(pos, m.index)));
        }
        const href = m[2];
        const label = formatReplyDisplay(m[1]);
        parts.push(
            `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`
        );
        pos = m.index + m[0].length;
    }
    if (pos < plainFirst.length) {
        parts.push(escapeHtml(plainFirst.slice(pos)));
    }
    return parts.join("") || escapeHtml(plainFirst);
};

const toMessageText = (value) => {
    if (value === null || value === undefined) {
        return "";
    }
    return String(value);
};

/**
 * Render a parsed quiz array as structured HTML card.
 * @param {Array} questions  [{number, question, options:{A,B,C,D}, answer}]
 * @returns {string}
 */
const renderQuizHtml = (questions) => {
    if (!Array.isArray(questions) || questions.length === 0) {
        return "";
    }
    return questions.map((q, idx) => {
        const opts = q.options || {};
        const ans = String(q.answer || "").trim().toUpperCase();
        const optLines = ["A", "B", "C", "D"]
            .filter((k) => opts[k] !== undefined)
            .map((k) => {
                const isCorrect = k === ans;
                const text = escapeHtml(String(opts[k] || ""));
                const cls = isCorrect
                    ? "local-chatbot-quiz-opt local-chatbot-quiz-opt-correct"
                    : "local-chatbot-quiz-opt";
                return `<div class="${cls}"><span class="local-chatbot-quiz-opt-key">${k}.</span> ${text}</div>`;
            })
            .join("");
        const ansText = opts[ans]
            ? `${ans}. ${escapeHtml(String(opts[ans]))}`
            : ans;
        const divider =
            idx < questions.length - 1
                ? '<hr class="local-chatbot-quiz-divider">'
                : "";
        return `<div class="local-chatbot-quiz-question">
<div class="local-chatbot-quiz-num">Quiz ${escapeHtml(String(q.number || idx + 1))}</div>
<div class="local-chatbot-quiz-q">${escapeHtml(String(q.question || ""))}</div>
<div class="local-chatbot-quiz-opts">${optLines}</div>
<div class="local-chatbot-quiz-answer">Jawaban: ✅ ${ansText}</div>
</div>${divider}`;
    }).join("");
};

const addMessage = (container, text, role) => {
    const safe = toMessageText(text);
    const message = document.createElement("div");
    message.className = `local-chatbot-msg ${role}`;
    if (role === "bot") {
        message.innerHTML = formatBotReplyHtml(safe);
    } else {
        message.textContent = safe;
    }
    container.appendChild(message);
    container.scrollTop = container.scrollHeight;
};

const clearMessages = (container) => {
    container.innerHTML = "";
};

const resolveCourseId = (serverCourseId) => {
    const fromServer = parseInt(serverCourseId, 10) || 0;
    if (fromServer > 1) {
        return fromServer;
    }
    if (typeof M !== "undefined" && M.cfg && M.cfg.courseId) {
        const fromCfg = parseInt(M.cfg.courseId, 10) || 0;
        if (fromCfg > 1) {
            return fromCfg;
        }
    }
    const path = window.location.pathname || "";
    if (!path.includes("course/view.php")) {
        return 0;
    }
    const raw = new URLSearchParams(window.location.search || "").get("id");
    const fromUrl = parseInt(raw || "", 10) || 0;
    return fromUrl > 1 ? fromUrl : 0;
};

const readFileAsBase64 = (file) =>
    new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const res = reader.result;
            const b64 =
                typeof res === "string" && res.includes(",")
                    ? res.split(",")[1]
                    : res;
            resolve({
                name: file.name,
                mime: file.type || "application/octet-stream",
                data_base64: b64,
            });
        };
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });

const showLoading = (container, label) => {
    const el = document.createElement("div");
    el.className = "local-chatbot-msg bot local-chatbot-loading";
    el.setAttribute("aria-live", "polite");
    el.textContent = label;
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
    return el;
};

const formatRoomTime = (unix) => {
    if (!unix) {
        return "";
    }
    const d = new Date(unix * 1000);
    return d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });
};

const ICON_MENU = `
<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
</svg>`;

const ICON_PLUS = `
<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
</svg>`;

const ICON_SEND = `
<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M2 21l21-9L2 3v7l15 2-15 2v7z" fill="currentColor"/>
</svg>`;

const ICON_TRASH = `
<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M9 4h6v1h7v2H2V5h7V4zm2 7h2v9h-2v-9zm5 0h2v9h-2v-9zM6 7h14l-1.2 13H7.2L6 7z" fill="currentColor"/>
</svg>`;

const ICON_CLOSE = `
<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
</svg>`;

const IMAGE_MIMES = new Set([
    "image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif",
]);

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "webp", "gif"]);

const isImageFile = (file) => {
    if (!file) {
        return false;
    }
    const mime = (file.type || "").toLowerCase();
    if (mime.startsWith("image/") || IMAGE_MIMES.has(mime)) {
        return true;
    }
    const ext = (file.name || "").split(".").pop()?.toLowerCase() || "";
    return IMAGE_EXT.has(ext);
};

const fileExtension = (name) => (name || "").split(".").pop()?.toLowerCase() || "";

const fileKey = (file) => `${file.name}:${file.size}:${file.lastModified}`;

const formatFileSize = (bytes) => {
    if (!bytes) {
        return "0 B";
    }
    const units = ["B", "KB", "MB", "GB"];
    let n = bytes;
    let i = 0;
    while (n >= 1024 && i < units.length - 1) {
        n /= 1024;
        i += 1;
    }
    return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
};

/**
 * @param {string} welcomeMessage
 * @param {string|number} courseId
 * @param {Record<string, string>} [strings]
 */
export const init = (welcomeMessage, courseId, strings = {}) => {
    if (document.querySelector(".local-chatbot-button")) {
        return;
    }

    const generating = strings.generating || "Generating answer…";
    const attachLabel = strings.attachfiles || "Attach files";
    const menuAttachLabel = strings.menuattach || "Attach image / file";
    const menuQuizLabel = strings.menugeneratequiz || "Generate quiz";
    const menuMoreLabel = strings.menumoreactions || "More actions";
    const quizModeLabel = strings.quizmodeactive || "Quiz mode";
    const quizPlaceholder =
        strings.quizmodeplaceholder ||
        "Describe your quiz (e.g. 10 multiple choice questions)…";
    const defaultInputPlaceholder =
        strings.inputplaceholder ||
        "Ask about your courses or company documents...";
    const historyTitle = strings.historytitle || "Chat history";
    const historySearch = strings.historysearch || "Search chats…";
    const historyEmpty = strings.historyempty || "No previous chats.";
    const panelTitle = strings.paneltitle || "Moda";
    const panelSubtitle = strings.panelsubtitle || "Moodle Assistant";
    const buttonLabel = strings.buttonlabel || "Moda";
    const deleteRoomAria = strings.deleteroomaria || "Delete conversation";
    const confirmDeleteRoom = strings.confirmdeleteroom || "Remove this conversation and all its messages?";
    const deleteAllLabel = strings.deleteall || "Clear all";
    const confirmDeleteAll = strings.confirmdeleteall || "Delete every saved chat in this list?";
    const deleteFailedMsg = strings.deletefailed || "Could not delete that chat.";
    const emptyReplyMsg =
        strings.emptyreply ||
        "The assistant returned no text. Try again from a course page.";
    const removeAttachmentLabel = strings.removeattachment || "Remove attachment";
    const closePreviewLabel = strings.closepreview || "Close preview";
    const previewUnavailableMsg =
        strings.previewunavailable ||
        "Preview is not available for this file type. The file will still be sent with your message.";
    const previewFileTitle = strings.previewfiletitle || "File preview";

    const cid = resolveCourseId(courseId);

    const root = document.querySelector(".local-chatbot-root") || document.body;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "local-chatbot-button";
    button.textContent = buttonLabel;

    const panel = document.createElement("section");
    panel.className = "local-chatbot-panel";

    const header = document.createElement("div");
    header.className = "local-chatbot-header";

    const menuBtn = document.createElement("button");
    menuBtn.type = "button";
    menuBtn.className = "local-chatbot-menu-btn";
    menuBtn.innerHTML = ICON_MENU;
    menuBtn.setAttribute("aria-label", historyTitle);
    menuBtn.title = historyTitle;

    const headerTitles = document.createElement("div");
    headerTitles.className = "local-chatbot-header-titles";

    const headerTitle = document.createElement("span");
    headerTitle.className = "local-chatbot-header-title";
    headerTitle.textContent = panelTitle;

    const headerSubtitle = document.createElement("span");
    headerSubtitle.className = "local-chatbot-header-subtitle";
    headerSubtitle.textContent = panelSubtitle;

    headerTitles.append(headerTitle, headerSubtitle);

    const closePanelBtn = document.createElement("button");
    closePanelBtn.type = "button";
    closePanelBtn.className = "local-chatbot-menu-btn local-chatbot-header-close";
    closePanelBtn.innerHTML = ICON_CLOSE;
    closePanelBtn.setAttribute("aria-label", strings.closepanel || "Close chat");
    closePanelBtn.title = strings.closepanel || "Close chat";

    header.append(menuBtn, headerTitles, closePanelBtn);

    const body = document.createElement("div");
    body.className = "local-chatbot-body";

    const messages = document.createElement("div");
    messages.className = "local-chatbot-messages";

    const drawer = document.createElement("aside");
    drawer.className = "local-chatbot-drawer";
    drawer.setAttribute("aria-hidden", "true");

    const drawerBackdrop = document.createElement("button");
    drawerBackdrop.type = "button";
    drawerBackdrop.className = "local-chatbot-drawer-backdrop";
    drawerBackdrop.setAttribute("aria-label", "Close history");

    const drawerPanel = document.createElement("div");
    drawerPanel.className = "local-chatbot-drawer-panel";

    const drawerHeader = document.createElement("div");
    drawerHeader.className = "local-chatbot-drawer-header";

    const drawerHeaderRow = document.createElement("div");
    drawerHeaderRow.className = "local-chatbot-drawer-header-row";

    const drawerHeaderTitle = document.createElement("span");
    drawerHeaderTitle.className = "local-chatbot-drawer-header-title";
    drawerHeaderTitle.textContent = historyTitle;

    const clearAllBtn = document.createElement("button");
    clearAllBtn.type = "button";
    clearAllBtn.className = "local-chatbot-drawer-clearall";
    clearAllBtn.textContent = deleteAllLabel;
    clearAllBtn.setAttribute("aria-label", deleteAllLabel);

    drawerHeaderRow.append(drawerHeaderTitle, clearAllBtn);
    drawerHeader.append(drawerHeaderRow);

    const searchInput = document.createElement("input");
    searchInput.type = "search";
    searchInput.className = "form-control local-chatbot-history-search";
    searchInput.placeholder = historySearch;

    const roomList = document.createElement("div");
    roomList.className = "local-chatbot-room-list";

    drawerPanel.append(drawerHeader, searchInput, roomList);
    drawer.append(drawerBackdrop, drawerPanel);

    const compose = document.createElement("div");
    compose.className = "local-chatbot-compose";

    const attachmentStrip = document.createElement("div");
    attachmentStrip.className = "local-chatbot-attachments";
    attachmentStrip.hidden = true;

    const inputRow = document.createElement("div");
    inputRow.className = "local-chatbot-inputrow";

    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.multiple = true;
    fileInput.className = "local-chatbot-fileinput";
    fileInput.setAttribute(
        "accept",
        [
            ".pdf", ".txt", ".csv", ".xlsx", ".xlsm", ".docx", ".pptx",
            ".png", ".jpg", ".jpeg", ".webp", ".gif", ".md", ".json",
        ].join(",")
    );

    const plusWrap = document.createElement("div");
    plusWrap.className = "local-chatbot-plus-wrap";

    const plusBtn = document.createElement("button");
    plusBtn.type = "button";
    plusBtn.className = "btn btn-secondary local-chatbot-plus local-chatbot-iconbtn";
    plusBtn.innerHTML = ICON_PLUS;
    plusBtn.title = menuMoreLabel;
    plusBtn.setAttribute("aria-label", menuMoreLabel);
    plusBtn.setAttribute("aria-haspopup", "true");
    plusBtn.setAttribute("aria-expanded", "false");

    const actionMenu = document.createElement("div");
    actionMenu.className = "local-chatbot-action-menu";
    actionMenu.setAttribute("role", "menu");
    actionMenu.hidden = true;

    const attachMenuItem = document.createElement("button");
    attachMenuItem.type = "button";
    attachMenuItem.className = "local-chatbot-action-menu-item";
    attachMenuItem.setAttribute("role", "menuitemcheckbox");
    attachMenuItem.setAttribute("aria-checked", "false");
    attachMenuItem.textContent = menuAttachLabel;

    const quizMenuItem = document.createElement("button");
    quizMenuItem.type = "button";
    quizMenuItem.className = "local-chatbot-action-menu-item";
    quizMenuItem.setAttribute("role", "menuitemcheckbox");
    quizMenuItem.setAttribute("aria-checked", "false");
    quizMenuItem.textContent = menuQuizLabel;

    actionMenu.append(attachMenuItem, quizMenuItem);
    plusWrap.append(plusBtn, actionMenu);

    const modeBadges = document.createElement("div");
    modeBadges.className = "local-chatbot-mode-badges";

    const quizBadge = document.createElement("span");
    quizBadge.className = "local-chatbot-mode-badge local-chatbot-mode-badge-quiz";
    quizBadge.textContent = quizModeLabel;
    quizBadge.hidden = true;
    modeBadges.appendChild(quizBadge);

    const input = document.createElement("input");
    input.type = "text";
    input.className = "form-control";
    input.placeholder = defaultInputPlaceholder;

    const send = document.createElement("button");
    send.type = "button";
    send.className = "btn btn-primary local-chatbot-send local-chatbot-iconbtn";
    send.innerHTML = ICON_SEND;
    send.title = "Send";
    send.setAttribute("aria-label", "Send");

    compose.append(attachmentStrip, inputRow);
    inputRow.append(plusWrap, input, send);
    body.append(messages, drawer);
    panel.append(header, body, modeBadges, compose);
    root.append(button, panel);
    root.appendChild(fileInput);

    const previewOverlay = document.createElement("div");
    previewOverlay.className = "local-chatbot-preview-overlay";
    previewOverlay.hidden = true;
    previewOverlay.setAttribute("role", "dialog");
    previewOverlay.setAttribute("aria-modal", "true");

    const previewBackdrop = document.createElement("button");
    previewBackdrop.type = "button";
    previewBackdrop.className = "local-chatbot-preview-backdrop";
    previewBackdrop.setAttribute("aria-label", closePreviewLabel);

    const previewDialog = document.createElement("div");
    previewDialog.className = "local-chatbot-preview-dialog";

    const previewClose = document.createElement("button");
    previewClose.type = "button";
    previewClose.className = "local-chatbot-preview-close";
    previewClose.innerHTML = ICON_CLOSE;
    previewClose.setAttribute("aria-label", closePreviewLabel);

    const previewBody = document.createElement("div");
    previewBody.className = "local-chatbot-preview-body";

    previewDialog.append(previewClose, previewBody);
    previewOverlay.append(previewBackdrop, previewDialog);
    panel.appendChild(previewOverlay);

    let currentRoomId = 0;
    let searchTimer = null;
    let pendingQuizJson = "";
    let quizModeActive = false;
    let stagedFiles = [];
    const objectUrlCache = new Map();

    const syncFileInputFromStaged = () => {
        if (typeof DataTransfer === "undefined") {
            return;
        }
        const dt = new DataTransfer();
        stagedFiles.forEach((f) => dt.items.add(f));
        fileInput.files = dt.files;
    };

    const getObjectUrl = (file) => {
        const key = fileKey(file);
        if (!objectUrlCache.has(key)) {
            objectUrlCache.set(key, URL.createObjectURL(file));
        }
        return objectUrlCache.get(key);
    };

    const revokeObjectUrl = (file) => {
        const key = fileKey(file);
        if (objectUrlCache.has(key)) {
            URL.revokeObjectURL(objectUrlCache.get(key));
            objectUrlCache.delete(key);
        }
    };

    const clearAllObjectUrls = () => {
        objectUrlCache.forEach((url) => URL.revokeObjectURL(url));
        objectUrlCache.clear();
    };

    const closePreview = () => {
        previewOverlay.hidden = true;
        previewBody.innerHTML = "";
        previewOverlay.removeAttribute("aria-label");
    };

    const openPreview = (title, contentNode) => {
        previewBody.innerHTML = "";
        previewOverlay.setAttribute("aria-label", title);
        previewBody.appendChild(contentNode);
        previewOverlay.hidden = false;
    };

    const showImagePreview = (file) => {
        const url = getObjectUrl(file);
        const img = document.createElement("img");
        img.className = "local-chatbot-preview-image";
        img.src = url;
        img.alt = file.name;
        openPreview(file.name, img);
    };

    const showFilePreview = (file) => {
        const ext = fileExtension(file.name);
        const url = getObjectUrl(file);

        if (ext === "pdf") {
            const iframe = document.createElement("iframe");
            iframe.className = "local-chatbot-preview-iframe";
            iframe.src = url;
            iframe.title = file.name;
            openPreview(file.name, iframe);
            return;
        }

        const textTypes = new Set(["txt", "md", "json", "csv"]);
        if (textTypes.has(ext)) {
            const reader = new FileReader();
            reader.onload = () => {
                const pre = document.createElement("pre");
                pre.className = "local-chatbot-preview-text";
                pre.textContent = String(reader.result || "");
                openPreview(file.name, pre);
            };
            reader.readAsText(file);
            return;
        }

        const info = document.createElement("div");
        info.className = "local-chatbot-preview-fileinfo";
        const title = document.createElement("strong");
        title.textContent = file.name;
        const meta = document.createElement("p");
        meta.textContent = `${formatFileSize(file.size)} · .${ext || "file"}`;
        const hint = document.createElement("p");
        hint.className = "local-chatbot-preview-hint";
        hint.textContent = previewUnavailableMsg;
        info.append(title, meta, hint);
        openPreview(previewFileTitle, info);
    };

    const removeStagedFile = (index) => {
        const removed = stagedFiles.splice(index, 1)[0];
        if (removed) {
            revokeObjectUrl(removed);
        }
        syncFileInputFromStaged();
        renderAttachmentPreviews();
        refreshInputModes();
    };

    const renderAttachmentPreviews = () => {
        attachmentStrip.innerHTML = "";
        attachmentStrip.hidden = stagedFiles.length === 0;
        compose.classList.toggle("has-attachments", stagedFiles.length > 0);

        stagedFiles.forEach((file, index) => {
            const chip = document.createElement("div");
            chip.className = "local-chatbot-attach-chip";

            const openBtn = document.createElement("button");
            openBtn.type = "button";
            openBtn.className = "local-chatbot-attach-chip-open";
            openBtn.setAttribute("aria-label", file.name);

            if (isImageFile(file)) {
                const thumb = document.createElement("img");
                thumb.className = "local-chatbot-attach-chip-img";
                thumb.src = getObjectUrl(file);
                thumb.alt = "";
                openBtn.appendChild(thumb);
                openBtn.addEventListener("click", () => showImagePreview(file));
            } else {
                const doc = document.createElement("div");
                doc.className = "local-chatbot-attach-chip-doc";
                const extLabel = document.createElement("span");
                extLabel.className = "local-chatbot-attach-chip-ext";
                extLabel.textContent = (fileExtension(file.name) || "file").toUpperCase();
                const name = document.createElement("span");
                name.className = "local-chatbot-attach-chip-name";
                name.textContent = file.name;
                doc.append(extLabel, name);
                openBtn.appendChild(doc);
                openBtn.addEventListener("click", () => showFilePreview(file));
            }

            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "local-chatbot-attach-chip-remove";
            removeBtn.innerHTML = ICON_CLOSE;
            removeBtn.setAttribute("aria-label", removeAttachmentLabel);
            removeBtn.title = removeAttachmentLabel;
            removeBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                removeStagedFile(index);
            });

            chip.append(openBtn, removeBtn);
            attachmentStrip.appendChild(chip);
        });
    };

    const setActionMenuOpen = (open) => {
        actionMenu.hidden = !open;
        plusBtn.setAttribute("aria-expanded", open ? "true" : "false");
        plusBtn.classList.toggle("is-open", open);
    };

    const refreshInputModes = () => {
        attachMenuItem.setAttribute("aria-checked", stagedFiles.length > 0 ? "true" : "false");
        attachMenuItem.classList.toggle("is-active", stagedFiles.length > 0);
        quizMenuItem.setAttribute("aria-checked", quizModeActive ? "true" : "false");
        quizMenuItem.classList.toggle("is-active", quizModeActive);
        quizBadge.hidden = !quizModeActive;
        input.placeholder = quizModeActive ? quizPlaceholder : defaultInputPlaceholder;
        inputRow.classList.toggle("quiz-mode", quizModeActive);
    };

    const showWelcome = () => {
        clearMessages(messages);
        addMessage(messages, welcomeMessage, "bot");
    };

    const setDrawerOpen = (open) => {
        drawer.classList.toggle("is-open", open);
        drawer.setAttribute("aria-hidden", open ? "false" : "true");
        panel.classList.toggle("history-open", open);
    };

    const fetchRooms = (search = "") =>
        Ajax.call([
            {
                methodname: "local_chatbot_list_rooms",
                args: {
                    courseid: cid,
                    search: search,
                },
            },
        ])[0]
            .then((data) => {
                renderRoomList(data.rooms || []);
            })
            .catch(Notification.exception);

    const createRoom = () =>
        Ajax.call([
            {
                methodname: "local_chatbot_create_room",
                args: {courseid: cid},
            },
        ])[0]
            .then((data) => {
                currentRoomId = data.roomid || 0;
                showWelcome();
                pendingQuizJson = "";
                quizModeActive = false;
                stagedFiles = [];
                clearAllObjectUrls();
                closePreview();
                syncFileInputFromStaged();
                renderAttachmentPreviews();
                refreshInputModes();
            })
            .catch(Notification.exception);

    const loadRoom = (roomid) => {
        if (!roomid) {
            return Promise.resolve();
        }
        currentRoomId = roomid;
        return Ajax.call([
            {
                methodname: "local_chatbot_get_history",
                args: {
                    courseid: cid,
                    roomid: roomid,
                },
            },
        ])[0]
            .then((data) => {
                clearMessages(messages);
                pendingQuizJson = "";
                const msgs = data.messages || [];
                if (msgs.length === 0) {
                    addMessage(messages, welcomeMessage, "bot");
                    return;
                }
                msgs.forEach((m) => {
                    const role = m.role === "user" ? "user" : "bot";
                    addMessage(messages, m.message || "", role);
                });
            })
            .catch(Notification.exception);
    };

    const maybeRefreshHistory = () => {
        if (!drawer.classList.contains("is-open")) {
            return Promise.resolve();
        }
        return fetchRooms(searchInput.value.trim());
    };

    const deleteRoomById = (roomid) => {
        if (!roomid) {
            return Promise.resolve();
        }
        return Ajax.call([
            {
                methodname: "local_chatbot_delete_room",
                args: {
                    courseid: cid,
                    roomid: roomid,
                },
            },
        ])[0]
            .then((data) => {
                if (!data || !data.success) {
                    Notification.addNotification({
                        message: deleteFailedMsg,
                        type: "error",
                    });
                    return;
                }
                const wasCurrent = roomid === currentRoomId;
                const next = wasCurrent ? createRoom() : Promise.resolve();
                return next.then(() => maybeRefreshHistory());
            })
            .catch(Notification.exception);
    };

    const deleteAllRooms = () =>
        Ajax.call([
            {
                methodname: "local_chatbot_delete_all_rooms",
                args: {courseid: cid},
            },
        ])[0]
            .then((data) => {
                if (!data || !data.success) {
                    Notification.addNotification({
                        message: deleteFailedMsg,
                        type: "error",
                    });
                    return;
                }
                return createRoom().then(() => maybeRefreshHistory());
            })
            .catch(Notification.exception);

    const renderRoomList = (rooms) => {
        roomList.innerHTML = "";
        if (!rooms || rooms.length === 0) {
            const empty = document.createElement("p");
            empty.className = "local-chatbot-history-empty";
            empty.textContent = historyEmpty;
            roomList.appendChild(empty);
            return;
        }
        rooms.forEach((room) => {
            const row = document.createElement("div");
            row.className = "local-chatbot-room-row";

            const item = document.createElement("button");
            item.type = "button";
            item.className = "local-chatbot-room-item";
            if (room.roomid === currentRoomId) {
                item.classList.add("is-active");
            }
            const title = document.createElement("span");
            title.className = "local-chatbot-room-item-title";
            title.textContent = room.title || "Chat";
            const preview = document.createElement("span");
            preview.className = "local-chatbot-room-item-preview";
            preview.textContent = room.preview || "";
            const time = document.createElement("span");
            time.className = "local-chatbot-room-item-time";
            time.textContent = formatRoomTime(room.timemodified);
            item.append(title, preview, time);
            item.addEventListener("click", () => {
                loadRoom(room.roomid);
                setDrawerOpen(false);
            });

            const delBtn = document.createElement("button");
            delBtn.type = "button";
            delBtn.className = "local-chatbot-room-delete";
            delBtn.innerHTML = ICON_TRASH;
            delBtn.setAttribute("aria-label", deleteRoomAria);
            delBtn.title = deleteRoomAria;
            delBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                // eslint-disable-next-line no-alert
                if (!window.confirm(confirmDeleteRoom)) {
                    return;
                }
                deleteRoomById(room.roomid);
            });

            const wrap = document.createElement("div");
            wrap.className = "local-chatbot-room-item-wrap";
            wrap.append(item, delBtn);
            row.appendChild(wrap);
            roomList.appendChild(row);
        });
    };

    const openNewChatSession = () => {
        setDrawerOpen(false);
        return createRoom();
    };

    const closePanel = () => {
        panel.classList.remove("is-open");
        setDrawerOpen(false);
        closePreview();
    };

    closePanelBtn.addEventListener("click", closePanel);

    clearAllBtn.addEventListener("click", () => {
        // eslint-disable-next-line no-alert
        if (!window.confirm(confirmDeleteAll)) {
            return;
        }
        deleteAllRooms();
    });

    menuBtn.addEventListener("click", () => {
        const willOpen = !drawer.classList.contains("is-open");
        if (willOpen) {
            fetchRooms(searchInput.value.trim());
        }
        setDrawerOpen(willOpen);
    });

    drawerBackdrop.addEventListener("click", () => {
        setDrawerOpen(false);
    });

    searchInput.addEventListener("input", () => {
        if (searchTimer) {
            clearTimeout(searchTimer);
        }
        searchTimer = setTimeout(() => {
            fetchRooms(searchInput.value.trim());
        }, 300);
    });

    button.addEventListener("click", () => {
        const wasOpen = panel.classList.contains("is-open");
        panel.classList.toggle("is-open");
        if (panel.classList.contains("is-open") && !wasOpen) {
            input.focus();
            openNewChatSession();
        }
    });

    plusBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        setActionMenuOpen(actionMenu.hidden);
    });

    attachMenuItem.addEventListener("click", (e) => {
        e.stopPropagation();
        setActionMenuOpen(false);
        fileInput.click();
    });

    quizMenuItem.addEventListener("click", (e) => {
        e.stopPropagation();
        quizModeActive = !quizModeActive;
        refreshInputModes();
        setActionMenuOpen(false);
        input.focus();
    });

    document.addEventListener("click", (e) => {
        if (!plusWrap.contains(e.target)) {
            setActionMenuOpen(false);
        }
    });

    previewBackdrop.addEventListener("click", closePreview);
    previewClose.addEventListener("click", closePreview);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !previewOverlay.hidden) {
            closePreview();
        }
    });

    fileInput.addEventListener("change", () => {
        const picked = Array.from(fileInput.files || []);
        picked.forEach((file) => {
            const exists = stagedFiles.some((s) => fileKey(s) === fileKey(file));
            if (!exists) {
                stagedFiles.push(file);
            }
        });
        syncFileInputFromStaged();
        renderAttachmentPreviews();
        refreshInputModes();
    });

    const submit = () => {
        const files = [...stagedFiles];
        let text = input.value.trim();
        if (!text && quizModeActive) {
            text = "Generate a quiz from the course materials.";
        }

        if (!text && files.length === 0) {
            return;
        }

        if (!currentRoomId) {
            Notification.addNotification({
                message: strings.openingchat || "Starting a new chat…",
                type: "info",
            });
            createRoom().then(() => submit());
            return;
        }

        const userLine =
            text ||
            (files.length ? `[${files.map((f) => f.name).join(", ")}]` : "");
        addMessage(messages, userLine, "user");
        input.value = "";

        let loadingEl = null;
        send.disabled = true;
        plusBtn.disabled = true;
        loadingEl = showLoading(messages, generating);

        const filePromise =
            files.length > 0
                ? Promise.all(files.map((f) => readFileAsBase64(f)))
                : Promise.resolve([]);

        filePromise
            .then((payload) => {
                let attachmentsjson = "";
                if (payload.length) {
                    attachmentsjson = JSON.stringify(payload);
                }
                stagedFiles = [];
                clearAllObjectUrls();
                syncFileInputFromStaged();
                renderAttachmentPreviews();
                refreshInputModes();
                return Ajax.call([
                    {
                        methodname: "local_chatbot_send_message",
                        args: {
                            courseid: cid,
                            roomid: currentRoomId,
                            message: text,
                            attachmentsjson: attachmentsjson,
                            pending_quiz_json: pendingQuizJson,
                            quiz_mode: quizModeActive,
                        },
                    },
                ])[0];
            })
            .then((data) => {
                if (loadingEl && loadingEl.parentNode) {
                    loadingEl.remove();
                }
                if (!data || typeof data !== "object") {
                    addMessage(messages, emptyReplyMsg, "bot");
                    return;
                }
                if (data.roomid && data.roomid !== currentRoomId) {
                    currentRoomId = data.roomid;
                }
                const errText =
                    data.error != null && String(data.error).trim() !== ""
                        ? String(data.error)
                        : "";
                if (errText) {
                    addMessage(messages, errText, "bot");
                    return;
                }

                pendingQuizJson = data.quiz_json || "";

                let botReply = "";
                if (typeof data.reply === "string") {
                    botReply = data.reply;
                } else if (data.reply != null) {
                    botReply = String(data.reply);
                }
                if (!botReply.trim()) {
                    botReply = emptyReplyMsg;
                }

                // Render structured quiz card whenever quiz_json has questions
                let _quizQuestions = [];
                if (pendingQuizJson) {
                    try { _quizQuestions = JSON.parse(pendingQuizJson); } catch (_) {}
                }
                const _hasQuiz = Array.isArray(_quizQuestions) && _quizQuestions.length > 0;

                if (_hasQuiz) {
                    // Structured quiz card
                    const card = document.createElement("div");
                    card.className = "local-chatbot-msg bot local-chatbot-quiz-card";
                    card.innerHTML = renderQuizHtml(_quizQuestions);
                    messages.appendChild(card);

                    if (!data.quiz_ready_for_pdf) {
                        // Confirmation prompt below the card
                        const hint = document.createElement("div");
                        hint.className = "local-chatbot-msg bot local-chatbot-quiz-hint";
                        hint.textContent = "Apakah kamu puas? Ketik \u2018Ya\u2019 atau \u2018Download PDF\u2019 untuk mengunduh, atau \u2018Ganti soal X\u2019 untuk mengganti soal tertentu.";
                        messages.appendChild(hint);
                    }
                } else {
                    addMessage(messages, botReply, "bot");
                }

                if (data.quiz_ready_for_pdf && pendingQuizJson) {
                    const _capturedQuizJson = pendingQuizJson;
                    const _coursename = strings.coursename || "Course";
                    const _lang = strings.language || "id";

                    // Build safe filename: quiz_CourseName.pdf
                    const _safeFilename = "quiz_"
                        + _coursename.replace(/[^a-zA-Z0-9\u00C0-\u024F\s-]/g, "")
                                     .trim().replace(/\s+/g, "_")
                        + ".pdf";

                    // Show "Membuat PDF…" placeholder while fetching
                    const pdfLinkWrap = document.createElement("div");
                    pdfLinkWrap.className = "local-chatbot-msg bot";
                    pdfLinkWrap.textContent = "Membuat PDF\u2026";
                    messages.appendChild(pdfLinkWrap);
                    messages.scrollTop = messages.scrollHeight;

                    fetch(M.cfg.wwwroot + "/local/chatbot/quiz_pdf.php", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({
                            quiz_json: _capturedQuizJson,
                            coursename: _coursename,
                            language: _lang,
                            sesskey: M.cfg.sesskey,
                        }),
                    })
                    .then((r) => {
                        if (!r.ok) { throw new Error("PDF generation failed"); }
                        return r.blob();
                    })
                    .then((blob) => {
                        const blobUrl = URL.createObjectURL(blob);

                        // Replace placeholder with the file link
                        pdfLinkWrap.textContent = "";

                        const docIcon = document.createElement("span");
                        docIcon.className = "local-chatbot-pdf-link-icon";
                        docIcon.setAttribute("aria-hidden", "true");
                        docIcon.innerHTML =
                            `<svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16"><path d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z"/></svg>`;

                        const fileLink = document.createElement("a");
                        fileLink.className = "local-chatbot-pdf-link";
                        fileLink.href = blobUrl;
                        fileLink.download = _safeFilename;
                        fileLink.textContent = _safeFilename;

                        pdfLinkWrap.append(docIcon, fileLink);
                        pendingQuizJson = "";
                        messages.scrollTop = messages.scrollHeight;
                    })
                    .catch(() => {
                        pdfLinkWrap.textContent = strings.pdferror || "Could not generate PDF.";
                    });
                }
            })
            .catch((err) => {
                if (loadingEl && loadingEl.parentNode) {
                    loadingEl.remove();
                }
                Notification.exception(err);
            })
            .finally(() => {
                send.disabled = false;
                plusBtn.disabled = false;
            });
    };

    send.addEventListener("click", submit);
    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            submit();
        }
    });
};
