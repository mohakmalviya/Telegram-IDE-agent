"""
TEAM_004: Structured progress extraction CDP script.

Separate module to keep the JS template literal out of ide_bridge.py
editing, since multi-line JS in Python triple-quotes is fragile to edit.

Returns a JSON object with:
- taskName: current step heading
- taskStatus: mode (Planning/Fast/etc)
- files: [{action, name, added, removed}, ...]
- commands: [{header, command, output, status}, ...]
- activityLogs: [text, ...]
- isGenerating: bool
- responseHtml: latest response innerHTML

DOM selectors verified by click_inspector.py (TEAM_003) analysis.
"""

STRUCTURED_PROGRESS_SCRIPT = r"""(() => {
    const panel = document.querySelector('.antigravity-agent-side-panel');
    if (!panel) return null;

    const result = {
        taskName: null,
        taskStatus: null,
        files: [],
        commands: [],
        activityLogs: [],
        isGenerating: false,
        responseHtml: null
    };

    // ── Stop button → isGenerating ──
    const stopEl = panel.querySelector('[data-tooltip-id="input-send-button-cancel-tooltip"]');
    if (stopEl) {
        result.isGenerating = true;
    } else {
        const STOP_PATS = [/^stop$/i, /^stop generating$/i, /^stop response$/i];
        for (const btn of panel.querySelectorAll('button, [role="button"]')) {
            const labels = [
                (btn.textContent || '').trim(),
                (btn.getAttribute('aria-label') || '').trim(),
            ];
            if (labels.some(l => STOP_PATS.some(p => p.test(l)))) {
                result.isGenerating = true;
                break;
            }
        }
    }

    // ── Task Status: mode selector (span.text-xs.select-none inside button.py-1) ──
    const modeBtn = panel.querySelector('button.py-1 span.text-xs.select-none');
    if (modeBtn) {
        result.taskStatus = (modeBtn.textContent || '').trim() || null;
    }

    // ── File edits: div.group.flex entries ──
    // Structure: div.group.flex > div.truncate > div.flex.min-w-0.flex-row
    //   contains span.shrink-0 ("Created"/"Analyzed") + filename span + +N/-N spans
    const fileGroups = panel.querySelectorAll('div.group.flex');
    const seenFiles = new Set();
    for (const fg of fileGroups) {
        const actionSpan = fg.querySelector('span.shrink-0');
        if (!actionSpan) continue;
        const action = (actionSpan.textContent || '').trim();
        if (!action) continue;

        // Filename: try span.inline-flex.break-all, then any inline-flex span
        const nameSpans = fg.querySelectorAll('span.inline-flex');
        let fileName = '';
        let lineRef = '';
        for (const ns of nameSpans) {
            const cls = ns.className || '';
            if (cls.includes('break-all')) {
                fileName = (ns.textContent || '').trim();
            }
            if (cls.includes('opacity-50') || cls.includes('ml-0.5')) {
                lineRef = (ns.textContent || '').trim();
            }
        }
        if (!fileName) {
            // Broader fallback: parse filename from concatenated text
            const allText = (fg.textContent || '').trim();
            // Remove action word and diff counts to isolate filename
            const match = allText.match(/(?:Created|Edited|Analyzed|Modified|Deleted|Wrote)\s*([\w._\/-]+(?:\.[\w]+)?)/i);
            if (match) fileName = match[1];
        }
        if (!fileName) continue;

        const key = action + ':' + fileName;
        if (seenFiles.has(key)) continue;
        seenFiles.add(key);

        // +N/-N line counts
        const addedSpan = fg.querySelector('span.text-green-500, span.text-green-600');
        const removedSpan = fg.querySelector('span.text-red-500, span.text-red-600');
        const added = addedSpan ? parseInt((addedSpan.textContent || '').replace(/[^0-9]/g, ''), 10) || 0 : 0;
        const removed = removedSpan ? parseInt((removedSpan.textContent || '').replace(/[^0-9]/g, ''), 10) || 0 : 0;

        result.files.push({
            action: action,
            name: fileName + (lineRef || ''),
            added: added,
            removed: removed
        });
    }

    // ── Commands: div with border + rounded-lg containing command output ──
    // Header span.opacity-60 ("Running background command") + pre for output
    const cmdBlocks = panel.querySelectorAll('div.rounded-lg.border');
    const seenCmds = new Set();
    for (const cb of cmdBlocks) {
        const headerSpan = cb.querySelector('span.opacity-60');
        if (!headerSpan) continue;
        const headerText = (headerSpan.textContent || '').trim();
        if (!headerText) continue;

        // Command text: look for a span with the command path
        const cmdSpan = cb.querySelector('span.opacity-80, span.font-mono');
        const cmdText = cmdSpan ? (cmdSpan.textContent || '').trim() : '';

        // Output: pre block
        const preEl = cb.querySelector('pre');
        const output = preEl ? (preEl.textContent || '').trim().slice(0, 300) : '';

        const key = headerText + ':' + cmdText;
        if (seenCmds.has(key)) continue;
        seenCmds.add(key);

        result.commands.push({
            header: headerText,
            command: cmdText.slice(0, 200),
            output: output,
            status: headerText.toLowerCase().includes('running') ? 'running' : 'completed'
        });
    }

    // ── Activity logs & task name ──
    // Task name: p inside div.sticky.top-0 (the step summary header)
    // Only use sticky headers — these are short task step descriptions.
    // Do NOT use ml-1.5 p elements — those contain full AI response text.
    const stickyHeaders = panel.querySelectorAll('div.sticky.top-0 p');
    const seenActivity = new Set();
    for (const p of stickyHeaders) {
        const text = (p.textContent || '').trim();
        if (text && text.length > 2 && text.length < 200 && !seenActivity.has(text)) {
            seenActivity.add(text);
            // The last sticky header is the current task name
            result.taskName = text;
            result.activityLogs.push(text);
        }
    }

    // ── Latest response HTML (same logic as RESPONSE_TEXT_SCRIPT) ──
    const responseNodes = panel.querySelectorAll('.leading-relaxed.select-text');
    for (let i = responseNodes.length - 1; i >= 0; i--) {
        const node = responseNodes[i];
        if (node.closest('details') || node.closest('.notify-user-container') || node.closest('[role="dialog"]')) continue;
        // Skip step detail containers
        if (node.closest('div.sticky')) continue;
        const text = (node.innerText || '').trim();
        if (!text || text.length < 2) continue;
        // Skip activity-like text
        const lower = text.toLowerCase();
        if (/^(?:analy[sz]ing|reading|writing|running|searching|planning|thinking|processing|creating|updating|deleting|building|executing|thought for)\b/i.test(lower) && text.length <= 300) continue;
        if (/^good\s*bad$/i.test(text.replace(/\s+/g, ' '))) continue;
        const clone = node.cloneNode(true);
        clone.querySelectorAll('style, script, svg').forEach(el => el.remove());
        result.responseHtml = clone.innerHTML || '';
        break;
    }

    return result;
})()"""
