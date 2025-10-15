// ==UserScript==
// @name         Instagram Media Collector -> JSON Export
// @namespace    https://github.com/
// @version      1.0
// @description  Collect media objects from instagram top_serp API responses and export as JSON (deduped by id). Intercepts XHR and fetch.
// @match        https://www.instagram.com/*
// @grant        none
// ==/UserScript==

(function () {
    'use strict';

    // --- State: Map keyed by media.id to avoid duplicates ---
    const collectedMedia = new Map();

    // --- Floating UI ---
    const ui = document.createElement('div');
    Object.assign(ui.style, {
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        zIndex: '999999',
        background: 'rgba(0,0,0,0.82)',
        color: '#fff',
        padding: '10px 14px',
        borderRadius: '8px',
        fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial',
        fontSize: '13px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '8px',
        boxShadow: '0 4px 12px rgba(0,0,0,0.35)',
        minWidth: '150px'
    });

    const countText = document.createElement('div');
    countText.textContent = 'Collected media: 0';
    countText.style.fontWeight = '600';

    const exportBtn = document.createElement('button');
    exportBtn.textContent = 'Export JSON';
    Object.assign(exportBtn.style, {
        cursor: 'pointer',
        border: 'none',
        borderRadius: '6px',
        padding: '6px 10px',
        background: '#0095f6',
        color: '#fff',
        fontWeight: '600'
    });

    const clearBtn = document.createElement('button');
    clearBtn.textContent = 'Clear';
    Object.assign(clearBtn.style, {
        cursor: 'pointer',
        border: 'none',
        borderRadius: '6px',
        padding: '6px 10px',
        background: '#444',
        color: '#fff'
    });

    ui.appendChild(countText);
    const btnRow = document.createElement('div');
    btnRow.style.display = 'flex';
    btnRow.style.gap = '8px';
    btnRow.appendChild(exportBtn);
    btnRow.appendChild(clearBtn);
    ui.appendChild(btnRow);
    document.body.appendChild(ui);

    function updateCount() {
        countText.textContent = `Collected media: ${collectedMedia.size}`;
    }

    clearBtn.addEventListener('click', () => {
        if (!confirm('Clear all collected media?')) return;
        collectedMedia.clear();
        updateCount();
    });

    exportBtn.addEventListener('click', () => {
        if (collectedMedia.size === 0) {
            alert('No media collected yet.');
            return;
        }
        const arr = Array.from(collectedMedia.values());
        const jsonStr = JSON.stringify(arr, null, 2); // pretty-printed

        const blob = new Blob([jsonStr], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'instagram_media_collected.json';
        a.click();
        // free the object URL after a short timeout
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    });

    // --- Extraction helper ---
    function extractMediaFromResponseJson(json) {
        try {
            if (!json || !json.media_grid || !Array.isArray(json.media_grid.sections)) return;
            for (const section of json.media_grid.sections) {
                const medias = section?.layout_content?.medias ?? [];
                for (const wrapper of medias) {
                    const media = wrapper?.media;
                    if (media && media.id) {
                        // store original media object (shallow clone to avoid accidental mutation)
                        collectedMedia.set(media.id, JSON.parse(JSON.stringify(media)));
                    }
                }
            }
            updateCount();
        } catch (e) {
            console.warn('[IG Collector] extractMedia failed', e);
        }
    }

    // --- XHR interception ---
    (function hookXHR() {
        const origOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function (method, url, ...rest) {
            this._interceptedUrl = url;
            return origOpen.call(this, method, url, ...rest);
        };

        const origSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.send = function (...args) {
            // attach load listener once
            this.addEventListener('load', function () {
                try {
                    const url = this._interceptedUrl || '';
                    if (typeof url === 'string' && url.includes('/api/v1/fbsearch/web/top_serp/')) {
                        // responseText can be large; guard with try/catch
                        let text = null;
                        try { text = this.responseText; } catch (e) { /* ignore */ }
                        if (text) {
                            try {
                                const json = JSON.parse(text);
                                extractMediaFromResponseJson(json);
                            } catch (e) {
                                // not JSON or parse error
                                // console.debug('[IG Collector] XHR non-json or parse error');
                            }
                        }
                    }
                } catch (e) {
                    console.warn('[IG Collector] xhr load handler', e);
                }
            }, { passive: true });
            return origSend.apply(this, args);
        };
    })();

    // --- fetch interception ---
    (function hookFetch() {
        if (!window.fetch) return;
        const origFetch = window.fetch;
        window.fetch = async function (...args) {
            try {
                const response = await origFetch.apply(this, args);
                try {
                    const requestUrl = (typeof args[0] === 'string') ? args[0] : (args[0]?.url || '');
                    if (typeof requestUrl === 'string' && requestUrl.includes('/api/v1/fbsearch/web/top_serp/')) {
                        // clone response so we can read it without disturbing page
                        const clone = response.clone();
                        // try to parse JSON
                        clone.text().then(text => {
                            try {
                                const json = JSON.parse(text);
                                extractMediaFromResponseJson(json);
                            } catch (e) {
                                // ignore parse errors
                            }
                        }).catch(() => { /* ignore */ });
                    }
                } catch (e) {
                    console.warn('[IG Collector] fetch inner', e);
                }
                return response;
            } catch (err) {
                // propagate fetch error
                throw err;
            }
        };
    })();

    console.log('[IG Media Collector] running — listening for top_serp responses.');
})();
