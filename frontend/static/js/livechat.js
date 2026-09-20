// Real-time Live Chat and WebSocket Manager
let activeCustomerId = null;
let activeCustomerName = '';
let activeBotPaused = false;
let socket = null;

// Audio notification using Web Audio API (No external sound file required!)
function playNotificationChime(frequency = 587.33, duration = 0.25) {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(frequency, audioCtx.currentTime); // D5
        osc.frequency.exponentialRampToValueAtTime(880, audioCtx.currentTime + duration); // A5
        gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + duration);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + duration);
    } catch (e) {
        console.debug('Audio chime not allowed yet:', e);
    }
}

// WebSocket connection
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/chat/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Connected to real-time WebSocket');
        const badge = document.getElementById('botStatusBadge');
        if (badge) {
            badge.innerText = '● სისტემა ონლაინია';
            badge.className = 'badge badge-success';
        }
    };

    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleIncomingWSEvent(data);
        } catch (e) {
            console.error('Error handling WS event:', e);
        }
    };

    socket.onclose = () => {
        console.log('WS disconnected, reconnecting in 3 seconds...');
        const badge = document.getElementById('botStatusBadge');
        if (badge) {
            badge.innerText = '○ კავშირი გაწყდა';
            badge.className = 'badge badge-warning';
        }
        setTimeout(initWebSocket, 3000);
    };
}

function handleIncomingWSEvent(data) {
    if (data.type === 'new_order') {
        playNotificationChime(659.25, 0.4); // Chime
        showToast(`🚨 ახალი შეკვეთა #${data.order.order_number} (${data.order.total_amount.toFixed(2)} GEL)!`);
        
        const badge = document.getElementById('newOrdersBadge');
        if (badge) {
            badge.style.display = 'inline-block';
            badge.innerText = parseInt(badge.innerText || '0') + 1;
        }

        // Refresh current view if relevant
        const currentPane = document.querySelector('.tab-pane.active');
        if (currentPane && currentPane.id === 'tab-dashboard') loadDashboard();
        if (currentPane && currentPane.id === 'tab-orders') loadOrders();
    }
    else if (data.type === 'human_handoff_requested') {
        playNotificationChime(440, 0.5);
        showToast(`🙋‍♂️ ${data.customer_name} ითხოვს ოპერატორს!`);
        const badge = document.getElementById('handoffBadge');
        if (badge) badge.style.display = 'inline-block';
        loadChatThreads();
    }
    else if (data.type === 'new_chat_message') {
        const msg = data.message;
        // If current active chat is this customer, append message immediately!
        if (activeCustomerId === msg.customer_id) {
            appendMessageBubble(msg.sender, msg.text, msg.timestamp, msg.media_url);
        }
        loadChatThreads(); // Refresh threads preview
    }
    else if (data.type === 'product_added_from_channel' || data.type === 'product_updated_by_assistant') {
        playNotificationChime(783.99, 0.3);
        if (data.type === 'product_updated_by_assistant') {
            showToast(`🤖 ასისტენტმა განაახლა: ${data.name} (${data.price}₾, მარაგი: ${data.stock})`);
        } else {
            showToast(`🎉 ჩანელიდან ავტომატურად დაემატა: ${data.product.name} (${data.product.price} GEL)!`);
        }
        const currentPane = document.querySelector('.tab-pane.active');
        if (currentPane && currentPane.id === 'tab-products') loadProducts();
        if (currentPane && currentPane.id === 'tab-dashboard') loadDashboard();
    }
    else if (data.type === 'order_updated_by_assistant' || data.type === 'receipt_uploaded') {
        if (data.type === 'receipt_uploaded') {
            playNotificationChime(659.25, 0.3);
            showToast(`🧾 ახალი ქვითარი შეკვეთაზე #${data.order_number}!`);
        }
        const currentPane = document.querySelector('.tab-pane.active');
        if (currentPane && currentPane.id === 'tab-orders') loadOrders();
        if (currentPane && currentPane.id === 'tab-dashboard') loadDashboard();
    }
    else if (data.type === 'receipt_verified') {
        playNotificationChime(880, 0.35);
        showToast(`✅ ქვითარი დამოწმდა AI-ის მიერ: #${data.order_number} (${data.extracted_amount} GEL)!`, 'success');
        const currentPane = document.querySelector('.tab-pane.active');
        if (currentPane && currentPane.id === 'tab-orders') loadOrders();
        if (currentPane && currentPane.id === 'tab-dashboard') loadDashboard();
    }
    else if (data.type === 'dashboard_reset') {
        loadDashboard();
    }
    else if (data.type === 'receipt_fraud_alert') {
        playNotificationChime(220, 0.7); // Low alert tone
        showToast(`🚨 ყალბი/შეუსაბამო ქვითარი #${data.order_number}! კლიენტი ${data.customer_name} გადავიდა Black List-ში!`, 'danger');
        const blBadge = document.getElementById('blacklistBadge');
        if (blBadge) {
            blBadge.style.display = 'inline-block';
            blBadge.innerText = parseInt(blBadge.innerText || '0') + 1;
        }
        const currentPane = document.querySelector('.tab-pane.active');
        if (currentPane && currentPane.id === 'tab-orders') loadOrders();
        if (currentPane && currentPane.id === 'tab-dashboard') loadDashboard();
        if (currentPane && currentPane.id === 'tab-blacklist' && typeof loadBlacklist === 'function') loadBlacklist();
    }
    else if (data.type === 'blacklist_updated') {
        if (typeof loadBlacklist === 'function') loadBlacklist();
    }
    else if (data.type === 'dashboard_reset') {
        if (typeof loadDashboard === 'function') loadDashboard();
    }
    else if (data.type === 'bot_status_toggled') {
        if (activeCustomerId === data.customer_id) {
            activeBotPaused = data.bot_paused;
            updateChatHeader();
        }
        loadChatThreads();
    }
}

// Load Chat Threads List
async function loadChatThreads() {
    try {
        const res = await fetch(`${API_BASE}/chat/threads`, { headers: getAuthHeaders() });
        if (res.status === 401) return;
        const threads = await res.json();
        const container = document.getElementById('chatThreadsList');
        if (!container) return;

        if (!threads.length) {
            container.innerHTML = '<div style="padding: 1rem; color: var(--text-muted); font-size: 0.85rem;">ჩატები ჯერ არ არის</div>';
            return;
        }

        container.innerHTML = threads.map(t => {
            const isActive = t.customer_id === activeCustomerId ? 'active' : '';
            const handoffBadge = t.bot_paused ? '<span class="badge badge-warning" style="font-size:0.65rem;">ოპერატორი</span>' : '';
            return `
                <div class="thread-item ${isActive}" onclick="selectChat(${t.customer_id}, '${t.name.replace(/'/g, "\\'")}', ${t.bot_paused})">
                    <div class="thread-name">
                        <span>${t.name}</span>
                        ${handoffBadge}
                    </div>
                    <div class="thread-preview">
                        <strong>${t.last_sender ? t.last_sender + ': ' : ''}</strong>${t.last_message || 'დიალოგი არ არის'}
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error('Error loading chat threads:', e);
    }
}

// Select customer chat
async function selectChat(customerId, customerName, isPaused) {
    activeCustomerId = customerId;
    activeCustomerName = customerName;
    activeBotPaused = isPaused;

    updateChatHeader();

    // Show input bar
    document.getElementById('chatInputBar').style.display = 'flex';

    // Highlight in list
    document.querySelectorAll('.thread-item').forEach(el => el.classList.remove('active'));

    // Load messages
    const box = document.getElementById('chatMessagesBox');
    box.innerHTML = '<div style="text-align:center; color: var(--text-muted); padding: 2rem;">იტვირთება...</div>';

    try {
        const res = await fetch(`${API_BASE}/chat/threads/${customerId}/messages`, { headers: getAuthHeaders() });
        const messages = await res.json();
        box.innerHTML = '';

        if (!messages.length) {
            box.innerHTML = '<div style="text-align:center; color: var(--text-muted); padding: 2rem;">შეტყობინებები არ არის</div>';
            return;
        }

        messages.forEach(m => {
            appendMessageBubble(m.sender, m.text, m.timestamp, m.media_url);
        });
        scrollChatToBottom();
    } catch (e) {
        console.error('Error loading messages:', e);
    }
}

function updateChatHeader() {
    const header = document.getElementById('chatWindowHeader');
    if (!header || !activeCustomerId) return;

    const pauseBtnText = activeBotPaused ? '▶️ ბოტის გააქტიურება' : '⏸ ბოტის დაპაუზება (ადამიანის ჩართვა)';
    const pauseBtnClass = activeBotPaused ? 'btn-success' : 'btn-warning';
    const statusBadge = activeBotPaused ? '<span class="badge badge-warning">ოპერატორის რეჟიმი</span>' : '<span class="badge badge-success">AI აქტიურია</span>';

    header.innerHTML = `
        <div style="display: flex; align-items: center; gap: 0.75rem;">
            <strong>${activeCustomerName}</strong>
            ${statusBadge}
        </div>
        <div>
            <button class="btn ${pauseBtnClass} btn-sm" onclick="toggleHumanHandoff()">${pauseBtnText}</button>
        </div>
    `;
}

function appendMessageBubble(sender, text, timestamp, mediaUrl = '') {
    const box = document.getElementById('chatMessagesBox');
    if (!box) return;

    const bubble = document.createElement('div');
    bubble.className = `bubble bubble-${sender}`;

    let senderLabel = '';
    if (sender === 'user') senderLabel = `<div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom: 2px;">👤 ${activeCustomerName}</div>`;
    else if (sender === 'ai') senderLabel = `<div style="font-size:0.75rem; color:#a5b4fc; margin-bottom: 2px;">🤖 Gemini 3.8 Flash</div>`;
    else if (sender === 'admin') senderLabel = `<div style="font-size:0.75rem; color:#6ee7b7; margin-bottom: 2px;">👨‍💼 ოპერატორი (თქვენ)</div>`;

    const timeStr = timestamp ? new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';

    let mediaHtml = '';
    if (mediaUrl) {
        mediaHtml = `
            <div style="margin: 6px 0;">
                <img src="${mediaUrl}" alt="მედია" style="max-width: 260px; max-height: 220px; border-radius: 8px; border: 1px solid var(--border); object-fit: cover; cursor: pointer; display: block;" onclick="viewReceipt('${mediaUrl}', 'მედია ფაილი')">
            </div>
        `;
    }

    bubble.innerHTML = `
        ${senderLabel}
        ${mediaHtml}
        <div>${text}</div>
        <div class="bubble-time">${timeStr}</div>
    `;

    box.appendChild(bubble);
    scrollChatToBottom();
}

function scrollChatToBottom() {
    const box = document.getElementById('chatMessagesBox');
    if (box) box.scrollTop = box.scrollHeight;
}

// Admin sends reply to customer
async function sendAdminReply() {
    const input = document.getElementById('adminMessageInput');
    const msg = input.value.trim();
    if (!msg || !activeCustomerId) return;

    input.value = '';

    try {
        const res = await fetch(`${API_BASE}/chat/threads/${activeCustomerId}/send`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ message: msg })
        });
        if (!res.ok) {
            const err = await res.json();
            alert(err.detail || 'გაგზავნის შეცდომა');
        }
    } catch (e) {
        console.error(e);
    }
}

// Toggle Human Handoff (Bot pause / resume)
async function toggleHumanHandoff() {
    if (!activeCustomerId) return;
    try {
        const res = await fetch(`${API_BASE}/chat/threads/${activeCustomerId}/toggle-bot`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
        const data = await res.json();
        activeBotPaused = data.bot_paused;
        updateChatHeader();
        showToast(activeBotPaused ? 'ბოტი დაპაუზდა. თქვენ ესაუბრებით კლიენტს!' : 'ბოტი კვლავ აქტიურია.');
    } catch (e) {
        console.error(e);
    }
}

// Telegram WebApp Initialization
function initTelegramMiniApp() {
    if (window.Telegram && window.Telegram.WebApp) {
        const tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand();
        console.log('Telegram WebApp initialized in theme:', tg.colorScheme);
    }
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    initWebSocket();
    initTelegramMiniApp();

    const input = document.getElementById('adminMessageInput');
    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') sendAdminReply();
        });
    }
});
