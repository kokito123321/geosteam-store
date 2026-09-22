// Main Application Logic
const API_BASE = '/api';

function getAuthHeaders() {
    const token = localStorage.getItem('auth_token');
    return {
        'Content-Type': 'application/json',
        'Authorization': token ? `Bearer ${token}` : ''
    };
}

// Check Auth on page load
function checkAuth() {
    const token = localStorage.getItem('auth_token');
    if (!token && window.location.pathname === '/admin') {
        window.location.href = '/login';
        return false;
    }
    const username = localStorage.getItem('username') || 'Admin';
    const role = localStorage.getItem('user_role') || 'Superadmin';
    const uEl = document.getElementById('currentUsername');
    const rEl = document.getElementById('currentUserRole');
    if (uEl) uEl.innerText = username;
    if (rEl) rEl.innerText = role;
    return true;
}

// Toast notification helper
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerText = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Navigation Tabs
function switchTab(tabId) {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(el => el.style.display = 'none');

    const targetNav = document.querySelector(`.nav-item[data-tab="${tabId}"]`);
    const targetPane = document.getElementById(`tab-${tabId}`);
    const titleEl = document.getElementById('pageTitle');

    if (targetNav) targetNav.classList.add('active');
    if (targetPane) targetPane.style.display = 'block';

    const titles = {
        'dashboard': 'მიმოხილვა',
        'products': 'პროდუქცია (E-Liquids)',
        'orders': 'შეკვეთები',
        'livechat': 'Live Chat & Human Handoff',
        'channel-posts': 'ჩანელის პოსტები (AI & Scheduler)',
        'ai-settings': 'Google Gemini AI პარამეტრები',
        'marketing': 'მარკეტინგი & Broadcast',
        'blacklist': '🚫 შავი სია (Black List) — თაღლითობის საწინააღმდეგო ფარი',
        'settings': 'მაღაზიის პარამეტრები'
    };
    if (titleEl) titleEl.innerText = titles[tabId] || 'მართვის პანელი';

    // Trigger tab-specific loads
    if (tabId === 'dashboard') loadDashboard();
    if (tabId === 'products') loadProducts();
    if (tabId === 'orders') loadOrders();
    if (tabId === 'livechat') loadChatThreads();
    if (tabId === 'channel-posts') loadChannelPosts();
    if (tabId === 'ai-settings') loadAISettings();
    if (tabId === 'marketing') { loadPromos(); }
    if (tabId === 'blacklist') loadBlacklist();
    if (tabId === 'settings') loadStoreSettings();
}

// --- 1. DASHBOARD & ANALYTICS ---
let revenueChartInstance = null;
let topFlavorsChartInstance = null;
let orderStatusChartInstance = null;

async function loadDashboard() {
    try {
        const [statsRes, analyticsRes] = await Promise.all([
            fetch(`${API_BASE}/dashboard/stats`, { headers: getAuthHeaders() }),
            fetch(`${API_BASE}/dashboard/analytics`, { headers: getAuthHeaders() })
        ]);

        if (statsRes.status === 401 || analyticsRes.status === 401) {
            window.location.href = '/login';
            return;
        }

        if (statsRes.ok) {
            const stats = await statsRes.json();
            const elRev = document.getElementById('metricTotalRevenue');
            const elOrd = document.getElementById('metricTotalOrders');
            const elProd = document.getElementById('metricActiveProducts');
            const elChats = document.getElementById('metricTotalChats');

            if (elRev) elRev.innerText = `${(stats.total_revenue || 0).toFixed(2)} GEL`;
            if (elOrd) elOrd.innerText = stats.total_orders || 0;
            if (elProd) elProd.innerText = stats.active_products || 0;
            if (elChats) elChats.innerText = stats.total_customers || 0;

            // Render Recent Orders
            const tbody = document.getElementById('dashboardRecentOrders');
            if (tbody) {
                if (!stats.recent_orders || !stats.recent_orders.length) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color: var(--text-muted);">შეკვეთები ჯერ არ არის</td></tr>';
                } else {
                    tbody.innerHTML = stats.recent_orders.map(o => `
                        <tr>
                            <td><strong>#${o.id}</strong></td>
                            <td>კლიენტი #${o.customer_id || 'N/A'}</td>
                            <td>${o.delivery_address || 'თბილისი'}</td>
                            <td><strong>${(o.total_amount || 0).toFixed(2)} GEL</strong></td>
                            <td>${o.delivery_method || 'courier'}</td>
                            <td>${o.payment_method || 'cash'}</td>
                            <td><span class="badge ${getStatusBadgeClass(o.order_status)}">${translateStatus(o.order_status)}</span></td>
                        </tr>
                    `).join('');
                }
            }
        }

        if (analyticsRes.ok) {
            const analytics = await analyticsRes.json();
            renderAnalyticsOverview(analytics);
        }

    } catch (err) {
        console.error('Error loading dashboard:', err);
    }
}

function renderAnalyticsOverview(data) {
    if (!data) return;

    // Financial summaries
    const fin = data.financial_summary || {};
    const elToday = document.getElementById('statTodayRevenue');
    const elWeek = document.getElementById('statWeekRevenue');
    const elMonth = document.getElementById('statMonthRevenue');
    const elAov = document.getElementById('statAvgOrderValue');

    if (elToday) elToday.innerText = `${(fin.today_revenue || 0).toFixed(2)} GEL`;
    if (elWeek) elWeek.innerText = `${(fin.week_revenue || 0).toFixed(2)} GEL`;
    if (elMonth) elMonth.innerText = `${(fin.month_revenue || 0).toFixed(2)} GEL`;
    if (elAov) elAov.innerText = `${(fin.avg_order_value || 0).toFixed(2)} GEL`;

    // Customer metrics
    const cust = data.customer_metrics || {};
    const elNewCust = document.getElementById('statNewCustomersWeek');
    const elRepeatRate = document.getElementById('statRepeatRate');
    if (elNewCust) elNewCust.innerText = cust.new_this_week || 0;
    if (elRepeatRate) elRepeatRate.innerText = `${cust.repeat_rate_percent || 0}%`;

    // Render Charts
    renderCharts(data);
}

function renderCharts(data) {
    if (typeof Chart === 'undefined') return;

    // 1. Revenue & Orders Trend Chart (Line + Bar)
    const trendCtx = document.getElementById('revenueTrendChart');
    if (trendCtx && data.daily_trends) {
        if (revenueChartInstance) revenueChartInstance.destroy();

        const labels = data.daily_trends.map(d => d.date.slice(5));
        const revenues = data.daily_trends.map(d => d.revenue);
        const orderCounts = data.daily_trends.map(d => d.orders_count);

        revenueChartInstance = new Chart(trendCtx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        type: 'line',
                        label: 'შემოსავალი (GEL)',
                        data: revenues,
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99, 102, 241, 0.15)',
                        borderWidth: 2.5,
                        tension: 0.35,
                        fill: true,
                        yAxisID: 'y'
                    },
                    {
                        type: 'bar',
                        label: 'შეკვეთები (#)',
                        data: orderCounts,
                        backgroundColor: 'rgba(16, 185, 129, 0.65)',
                        borderRadius: 6,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { labels: { color: '#94a3b8', font: { family: 'FiraGO' } } }
                },
                scales: {
                    x: {
                        ticks: { color: '#94a3b8' },
                        grid: { color: 'rgba(255, 255, 255, 0.05)' }
                    },
                    y: {
                        type: 'linear',
                        position: 'left',
                        ticks: { color: '#6366f1' },
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        title: { display: true, text: 'GEL', color: '#6366f1' }
                    },
                    y1: {
                        type: 'linear',
                        position: 'right',
                        ticks: { color: '#10b981', precision: 0 },
                        grid: { drawOnChartArea: false },
                        title: { display: true, text: 'რაოდენობა', color: '#10b981' }
                    }
                }
            }
        });
    }

    // 2. Top Flavors / Liquids Chart (Doughnut)
    const flavorsCtx = document.getElementById('topFlavorsChart');
    if (flavorsCtx && data.top_products) {
        if (topFlavorsChartInstance) topFlavorsChartInstance.destroy();

        const topP = data.top_products.slice(0, 5);
        const pLabels = topP.map(p => p.name.length > 20 ? p.name.slice(0, 20) + '...' : p.name);
        const pCounts = topP.map(p => p.sales_count > 0 ? p.sales_count : 1);

        topFlavorsChartInstance = new Chart(flavorsCtx, {
            type: 'doughnut',
            data: {
                labels: pLabels,
                datasets: [{
                    data: pCounts,
                    backgroundColor: [
                        '#6366f1',
                        '#ec4899',
                        '#10b981',
                        '#f59e0b',
                        '#06b6d4'
                    ],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#94a3b8', font: { family: 'FiraGO', size: 11 }, boxWidth: 12 }
                    }
                }
            }
        });
    }

    // 3. Order Status Breakdown (Pie)
    const statusCtx = document.getElementById('orderStatusChart');
    if (statusCtx && data.status_distribution) {
        if (orderStatusChartInstance) orderStatusChartInstance.destroy();

        const dist = data.status_distribution;
        const labels = ['ჩაბარებული', 'მზადდება / Paid', 'ახალი', 'გაუქმებული'];
        const values = [
            dist.delivered || 0,
            dist.processing || dist.paid || 0,
            dist.new || 0,
            dist.cancelled || 0
        ];

        orderStatusChartInstance = new Chart(statusCtx, {
            type: 'pie',
            data: {
                labels: labels,
                datasets: [{
                    data: values.some(v => v > 0) ? values : [1],
                    backgroundColor: [
                        '#10b981',
                        '#6366f1',
                        '#f59e0b',
                        '#ef4444'
                    ],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'right',
                        labels: { color: '#94a3b8', font: { family: 'FiraGO', size: 11 } }
                    }
                }
            }
        });
    }
}

async function triggerManualBackup() {
    showToast('⏳ მზადდება მონაცემთა ბაზის Backup...', 'info');
    try {
        const res = await fetch(`${API_BASE}/settings/backup/create`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Backup წარმატებით გაიგზავნა Telegram-ში!', 'success');
        } else {
            showToast(data.detail || 'შეცდომა Backup-ის შექმნისას', 'error');
        }
    } catch (err) {
        console.error('Error triggering backup:', err);
        showToast('სერვერთან კავშირის შეცდომა', 'error');
    }
}

async function confirmResetMetric(metricType) {
    const names = {
        'revenue': 'ჯამური შემოსავლისა და შეკვეთების ისტორიის',
        'orders': 'სულ შეკვეთების ისტორიის',
        'products': 'აქტიური სითხეების მარაგების (0-ზე დაყენება)',
        'chats': 'მომხმარებელთა ჩატების ისტორიის',
        'all': 'ყველა მეტრიკის'
    };
    const name = names[metricType] || metricType;
    if (!confirm(`ნამდვილად გსურთ ${name} განულება? ეს მოქმედება შეუქცევადია.`)) {
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/dashboard/reset-metric`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ metric: metricType })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'მეტრიკა წარმატებით განულდა!', 'success');
            loadDashboard();
        } else {
            showToast(data.detail || 'შეცდომა განულებისას', 'error');
        }
    } catch (err) {
        console.error('Error resetting metric:', err);
        showToast('სერვერთან კავშირის შეცდომა', 'error');
    }
}

function translateStatus(status) {
    const map = {
        'new': 'ახალი',
        'processing': 'მზადდება',
        'delivered': 'ჩაბარებული',
        'cancelled': 'გაუქმებული'
    };
    return map[status] || status;
}

function getStatusBadgeClass(status) {
    if (status === 'new') return 'badge-primary';
    if (status === 'processing') return 'badge-warning';
    if (status === 'delivered') return 'badge-success';
    if (status === 'cancelled') return 'badge-danger';
    return 'badge-primary';
}

// --- 2. PRODUCTS ---
async function loadProducts() {
    try {
        const res = await fetch(`${API_BASE}/products`);
        const products = await res.json();
        const tbody = document.getElementById('productsTableBody');
        const selectAll = document.getElementById('selectAllProducts');
        const bulkBtn = document.getElementById('bulkDeleteBtn');

        if (selectAll) selectAll.checked = false;
        if (bulkBtn) bulkBtn.style.display = 'none';

        if (!products.length) {
            tbody.innerHTML = '<tr><td colspan="11" style="text-align:center; color: var(--text-muted);">პროდუქცია არ არის დამატებული</td></tr>';
            return;
        }

        tbody.innerHTML = products.map(p => `
            <tr>
                <td style="text-align: center;">
                    <input type="checkbox" class="prod-select-chk" value="${p.id}" onchange="onProductSelectChange()">
                </td>
                <td>#${p.id}</td>
                <td><strong>${p.name}</strong></td>
                <td><strong>${p.price.toFixed(2)} GEL</strong></td>
                <td>${p.volume_ml} ml</td>
                <td><span class="badge badge-primary">${p.vg_pg_ratio}</span></td>
                <td><span class="badge badge-warning">${p.nicotine_mg}</span></td>
                <td>${p.stock_quantity} ცალი</td>
                <td>
                    <label class="switch">
                        <input type="checkbox" ${p.is_active ? 'checked' : ''} onchange="toggleProductStock(${p.id})">
                        <span class="slider"></span>
                    </label>
                </td>
                <td>
                    ${p.channel_post_url ? `<a href="${p.channel_post_url}" target="_blank" style="color: var(--primary);">ნახვა ↗</a>` : '-'}
                </td>
                <td>
                    <button class="btn btn-secondary btn-sm" onclick='editProduct(${JSON.stringify(p)})'>✏️</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteProduct(${p.id})">🗑️</button>
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Error loading products:', err);
    }
}

function toggleSelectAllProducts(master) {
    const checkboxes = document.querySelectorAll('.prod-select-chk');
    checkboxes.forEach(cb => cb.checked = master.checked);
    onProductSelectChange();
}

function onProductSelectChange() {
    const checked = document.querySelectorAll('.prod-select-chk:checked');
    const bulkBtn = document.getElementById('bulkDeleteBtn');
    const countEl = document.getElementById('selectedCount');
    const selectAll = document.getElementById('selectAllProducts');
    const all = document.querySelectorAll('.prod-select-chk');

    if (countEl) countEl.innerText = checked.length;
    if (bulkBtn) {
        bulkBtn.style.display = checked.length > 0 ? 'inline-block' : 'none';
    }
    if (selectAll && all.length > 0) {
        selectAll.checked = checked.length === all.length;
    }
}

async function bulkDeleteSelectedProducts() {
    const checked = document.querySelectorAll('.prod-select-chk:checked');
    const ids = Array.from(checked).map(cb => parseInt(cb.value));
    if (!ids.length) return;

    if (!confirm(`ნამდვილად გსურთ მონიშნული ${ids.length} პროდუქტის წაშლა?`)) return;

    try {
        const res = await fetch(`${API_BASE}/products/bulk-delete`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ product_ids: ids })
        });
        if (res.ok) {
            const data = await res.json();
            showToast(`წარმატებით წაიშალა ${data.deleted_count} პროდუქტი`);
            loadProducts();
        } else {
            const err = await res.json();
            alert(err.detail || 'შეცდომა წაშლისას');
        }
    } catch (e) {
        console.error('Bulk delete error:', e);
    }
}

async function toggleProductStock(id) {
    try {
        const res = await fetch(`${API_BASE}/products/${id}/toggle-stock`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
        if (res.ok) {
            showToast('მარაგის სტატუსი განახლდა');
        }
    } catch (err) {
        console.error(err);
    }
}

function openProductModal(prod = null) {
    const modal = document.getElementById('productModal');
    const title = document.getElementById('productModalTitle');
    document.getElementById('modalProductId').value = prod ? prod.id : '';
    document.getElementById('modalProdName').value = prod ? prod.name : '';
    document.getElementById('modalProdPrice').value = prod ? prod.price : '';
    document.getElementById('modalProdVolume').value = prod ? prod.volume_ml : '30';
    document.getElementById('modalProdVgPg').value = prod ? prod.vg_pg_ratio : '50/50';
    document.getElementById('modalProdNicotine').value = prod ? prod.nicotine_mg : '20mg';
    document.getElementById('modalProdStock').value = prod ? prod.stock_quantity : '10';
    document.getElementById('modalProdColorType').value = prod ? prod.color_type : 'Salt Nicotine';
    document.getElementById('modalProdDesc').value = prod ? prod.description : '';
    document.getElementById('modalProdChannelUrl').value = prod ? prod.channel_post_url : '';
    document.getElementById('modalProdPhotoUrl').value = prod ? prod.photo_url : '';

    title.innerText = prod ? 'სითხის რედაქტირება' : 'ახალი ვეიპ სითხის დამატება';
    modal.style.display = 'flex';
}

function closeProductModal() {
    document.getElementById('productModal').style.display = 'none';
}

function editProduct(prod) {
    openProductModal(prod);
}

async function saveProduct() {
    const id = document.getElementById('modalProductId').value;
    const body = {
        name: document.getElementById('modalProdName').value.trim(),
        price: parseFloat(document.getElementById('modalProdPrice').value),
        volume_ml: parseInt(document.getElementById('modalProdVolume').value) || 30,
        vg_pg_ratio: document.getElementById('modalProdVgPg').value.trim(),
        nicotine_mg: document.getElementById('modalProdNicotine').value.trim(),
        stock_quantity: parseInt(document.getElementById('modalProdStock').value) || 0,
        color_type: document.getElementById('modalProdColorType').value.trim(),
        description: document.getElementById('modalProdDesc').value.trim(),
        channel_post_url: document.getElementById('modalProdChannelUrl').value.trim(),
        photo_url: document.getElementById('modalProdPhotoUrl').value.trim()
    };

    if (!body.name || isNaN(body.price)) {
        alert('გთხოვთ შეავსოთ დასახელება და ფასი');
        return;
    }

    try {
        const url = id ? `${API_BASE}/products/${id}` : `${API_BASE}/products`;
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
            method: method,
            headers: getAuthHeaders(),
            body: JSON.stringify(body)
        });
        if (res.ok) {
            closeProductModal();
            showToast(id ? 'პროდუქტი განახლდა' : 'ახალი სითხე დაემატა');
            loadProducts();
        } else {
            const err = await res.json();
            alert(err.detail || 'შეცდომა შენახვისას');
        }
    } catch (e) {
        console.error(e);
    }
}

async function deleteProduct(id) {
    if (!confirm('ნამდვილად გსურთ პროდუქტის წაშლა?')) return;
    try {
        const res = await fetch(`${API_BASE}/products/${id}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });
        if (res.ok) {
            showToast('პროდუქტი წაიშალა');
            loadProducts();
        }
    } catch (e) {
        console.error(e);
    }
}

// --- 3. ORDERS ---
async function loadOrders() {
    try {
        const filter = document.getElementById('orderStatusFilter').value;
        const url = filter ? `${API_BASE}/orders?status=${filter}` : `${API_BASE}/orders`;
        const res = await fetch(url, { headers: getAuthHeaders() });
        const orders = await res.json();
        const tbody = document.getElementById('ordersTableBody');

        if (!orders.length) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color: var(--text-muted);">შეკვეთები არ მოიძებნა</td></tr>';
            return;
        }

        tbody.innerHTML = orders.map(o => {
            let itemsHtml = '';
            try {
                const items = JSON.parse(o.items_json);
                itemsHtml = items.map(i => `• ${i.name} (${i.nicotine_mg || ''}) x${i.quantity}`).join('<br>');
            } catch(e) { itemsHtml = 'N/A'; }

            const mapLoc = (o.location_lat && o.location_lng)
                ? `<br><a href="https://www.google.com/maps?q=${o.location_lat},${o.location_lng}" target="_blank" style="color:var(--primary);">📍 რუკა</a>`
                : '';

            const receiptHtml = o.receipt_image_url
                ? `
                    <div style="margin-top: 6px; display: flex; align-items: center; gap: 6px;">
                        <img src="${o.receipt_image_url}" alt="ქვითარი" 
                             style="width: 44px; height: 44px; object-fit: cover; border-radius: 6px; border: 1.5px solid var(--primary); cursor: pointer; transition: transform 0.2s;" 
                             onmouseover="this.style.transform='scale(1.08)'" 
                             onmouseout="this.style.transform='scale(1)'"
                             onclick="viewReceipt('${o.receipt_image_url}', '${o.order_number}', ${o.id}, ${o.total_amount}, '${(o.customer_name || '').replace(/'/g, "\\'")}')" 
                             title="დააჭირეთ გასადიდებლად">
                        <button class="btn btn-primary btn-sm" style="font-size:0.7rem; padding: 3px 6px;" 
                                onclick="viewReceipt('${o.receipt_image_url}', '${o.order_number}', ${o.id}, ${o.total_amount}, '${(o.customer_name || '').replace(/'/g, "\\'")}')">
                            🔍 ქვითარი
                        </button>
                    </div>
                  `
                : '';

            const notesHtml = o.notes ? `
                <div style="margin-top: 6px; font-size: 0.76rem; background: rgba(99, 102, 241, 0.12); border-left: 3px solid var(--primary); padding: 4px 8px; border-radius: 4px; color: var(--text);">
                    💬 <strong>მომხმარებლის მოწერილი:</strong> ${escapeHtml(o.notes)}
                </div>
            ` : '';

            let deliveryBadge = `<span class="badge" style="background: rgba(99, 102, 241, 0.15); color: var(--primary); font-size: 0.76rem;">${escapeHtml(o.delivery_method || 'მიწოდება')}</span>`;
            if ((o.delivery_method || '').includes('Yandex') || (o.delivery_method || '').includes('თბილისი')) {
                deliveryBadge = `<span class="badge" style="background: rgba(245, 158, 11, 0.15); color: #f59e0b; font-size: 0.76rem;">🛵 Yandex თბილისი</span>`;
            } else if ((o.delivery_method || '').includes('სოფელ')) {
                deliveryBadge = `<span class="badge" style="background: rgba(139, 92, 246, 0.15); color: #8b5cf6; font-size: 0.76rem;">🏡 რეგიონი (სოფელი 12₾)</span>`;
            } else if ((o.delivery_method || '').includes('რეგიონ') || (o.delivery_method || '').includes('ცენტრ')) {
                deliveryBadge = `<span class="badge" style="background: rgba(59, 130, 246, 0.15); color: #3b82f6; font-size: 0.76rem;">🏙️ რეგიონი (ცენტრი 9₾)</span>`;
            } else if ((o.delivery_method || '').includes('თვითგატან')) {
                deliveryBadge = `<span class="badge badge-success" style="font-size: 0.76rem;">🏬 თვითგატანა (მაღაზია)</span>`;
            }

            const addressHtml = o.delivery_address ? `<div style="margin-top: 4px; font-size: 0.78rem; font-weight: 500; color: var(--text);">📍 ${escapeHtml(o.delivery_address)}</div>` : '';

            return `
                <tr>
                    <td><strong>#${o.order_number}</strong></td>
                    <td>
                        <strong>${o.customer_name}</strong><br>
                        <small style="color:var(--text-secondary)">${o.customer_phone || 'ნომრის გარეშე'}</small>
                    </td>
                    <td>
                        <small>${itemsHtml}</small>
                        ${notesHtml}
                    </td>
                    <td><strong>${o.total_amount.toFixed(2)} GEL</strong></td>
                    <td>
                        ${deliveryBadge}
                        ${addressHtml}
                        ${mapLoc}
                    </td>
                    <td>
                        <span class="badge badge-primary">${o.payment_method} (${o.payment_status})</span>
                        ${receiptHtml}
                    </td>
                    <td>
                        <select class="btn btn-secondary btn-sm" onchange="updateOrderStatus(${o.id}, this.value)">
                            <option value="new" ${o.order_status === 'new' ? 'selected' : ''}>ახალი</option>
                            <option value="processing" ${o.order_status === 'processing' ? 'selected' : ''}>მზადდება</option>
                            <option value="delivered" ${o.order_status === 'delivered' ? 'selected' : ''}>ჩაბარებული</option>
                            <option value="cancelled" ${o.order_status === 'cancelled' ? 'selected' : ''}>გაუქმებული</option>
                        </select>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error(e);
    }
}

let currentReceiptZoom = 1.0;
let currentReceiptOrderId = null;
let isDraggingReceipt = false;
let receiptStartX = 0, receiptStartY = 0, receiptScrollLeft = 0, receiptScrollTop = 0;

function viewReceipt(url, orderNum, orderId = null, totalAmount = null, customerName = null) {
    const modal = document.getElementById('receiptModal');
    const img = document.getElementById('receiptModalImg');
    const title = document.getElementById('receiptModalTitle');
    const link = document.getElementById('receiptDownloadBtn');
    const infoPill = document.getElementById('receiptOrderInfoPill');
    currentReceiptOrderId = orderId;
    currentReceiptZoom = 1.0;

    if (title) title.innerHTML = `<span>🔍</span> ქვითრის შემოწმება: #${orderNum || ''}`;
    if (img) {
        img.src = url;
        img.style.transform = 'scale(1.0)';
        img.style.maxWidth = '90%';
        img.style.maxHeight = '85%';
    }
    if (link) link.href = url;
    const zoomLabel = document.getElementById('receiptZoomLevel');
    if (zoomLabel) zoomLabel.innerText = '100%';

    if (infoPill) {
        let infoText = `🔖 შეკვეთა: #${orderNum || ''}`;
        if (totalAmount) infoText += ` | 💰 თანხა: <strong>${parseFloat(totalAmount).toFixed(2)} GEL</strong>`;
        if (customerName) infoText += ` | 👤 კლიენტი: <strong>${customerName}</strong>`;
        infoPill.innerHTML = infoText;
    }

    if (modal) modal.style.display = 'flex';
    initReceiptDrag();
}

function zoomReceipt(delta) {
    currentReceiptZoom = Math.max(0.5, Math.min(3.5, currentReceiptZoom + delta));
    const img = document.getElementById('receiptModalImg');
    const label = document.getElementById('receiptZoomLevel');
    if (img) {
        img.style.transform = `scale(${currentReceiptZoom})`;
        if (currentReceiptZoom > 1.0) {
            img.style.maxWidth = 'none';
            img.style.maxHeight = 'none';
        } else {
            img.style.maxWidth = '90%';
            img.style.maxHeight = '85%';
        }
    }
    if (label) label.innerText = `${Math.round(currentReceiptZoom * 100)}%`;
}

function resetReceiptZoom() {
    currentReceiptZoom = 1.0;
    const img = document.getElementById('receiptModalImg');
    const label = document.getElementById('receiptZoomLevel');
    if (img) {
        img.style.transform = 'scale(1.0)';
        img.style.maxWidth = '90%';
        img.style.maxHeight = '85%';
    }
    if (label) label.innerText = '100%';
    const vp = document.getElementById('receiptViewport');
    if (vp) {
        vp.scrollLeft = 0;
        vp.scrollTop = 0;
    }
}

function initReceiptDrag() {
    const vp = document.getElementById('receiptViewport');
    if (!vp || vp.dataset.dragInit) return;
    vp.dataset.dragInit = 'true';

    vp.addEventListener('mousedown', (e) => {
        isDraggingReceipt = true;
        vp.style.cursor = 'grabbing';
        receiptStartX = e.pageX - vp.offsetLeft;
        receiptStartY = e.pageY - vp.offsetTop;
        receiptScrollLeft = vp.scrollLeft;
        receiptScrollTop = vp.scrollTop;
    });
    vp.addEventListener('mouseleave', () => {
        isDraggingReceipt = false;
        vp.style.cursor = 'grab';
    });
    vp.addEventListener('mouseup', () => {
        isDraggingReceipt = false;
        vp.style.cursor = 'grab';
    });
    vp.addEventListener('mousemove', (e) => {
        if (!isDraggingReceipt) return;
        e.preventDefault();
        const x = e.pageX - vp.offsetLeft;
        const y = e.pageY - vp.offsetTop;
        const walkX = (x - receiptStartX) * 1.5;
        const walkY = (y - receiptStartY) * 1.5;
        vp.scrollLeft = receiptScrollLeft - walkX;
        vp.scrollTop = receiptScrollTop - walkY;
    });
}

async function approveCurrentReceipt() {
    if (!currentReceiptOrderId) {
        alert('შეკვეთის ID ვერ მოიძებნა');
        return;
    }
    if (!confirm('ნამდვილად ადასტურებთ გადახდას? შეკვეთა გადავა მომზადების ეტაპზე და მომხმარებელს გაეგზავნება დადასტურების შეტყობინება ტელეგრამში.')) return;
    try {
        const res = await fetch(`${API_BASE}/orders/${currentReceiptOrderId}/approve-receipt`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
        if (res.ok) {
            showToast('✅ გადახდა დადასტურებულია! შეკვეთა გადავიდა მომზადებაზე.');
            closeReceiptModal();
            loadOrders();
            loadDashboard();
        } else {
            alert('დადასტურების შეცდომა');
        }
    } catch (e) {
        console.error(e);
    }
}

async function rejectCurrentReceipt() {
    if (!currentReceiptOrderId) return;
    const reason = prompt('მიუთითეთ უარყოფის მიზეზი (არასწორი თანხა, გაურკვეველი ქვითარი და ა.შ.):', 'არასწორი თანხა ან რეკვიზიტი');
    if (reason === null) return;
    try {
        const res = await fetch(`${API_BASE}/orders/${currentReceiptOrderId}/reject-receipt`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ reason: reason })
        });
        if (res.ok) {
            showToast('❌ ქვითარი უარყოფილია. კლიენტს გაეგზავნა შეტყობინება.');
            closeReceiptModal();
            loadOrders();
            loadDashboard();
        } else {
            alert('შეცდომა');
        }
    } catch (e) {
        console.error(e);
    }
}

function closeReceiptModal() {
    const modal = document.getElementById('receiptModal');
    if (modal) modal.style.display = 'none';
}

async function updateOrderStatus(orderId, newStatus) {
    try {
        const res = await fetch(`${API_BASE}/orders/${orderId}`, {
            method: 'PATCH',
            headers: getAuthHeaders(),
            body: JSON.stringify({ order_status: newStatus })
        });
        if (res.ok) {
            showToast(`შეკვეთის სტატუსი შეიცვალა: ${translateStatus(newStatus)}`);
        }
    } catch (e) {
        console.error(e);
    }
}

// --- 4. AI & GEMINI SETTINGS ---
async function loadAISettings() {
    try {
        const res = await fetch(`${API_BASE}/settings`, { headers: getAuthHeaders() });
        const data = await res.json();
        const modelSelect = document.getElementById('geminiModelSelect');
        if (modelSelect) modelSelect.value = data.gemini_model || 'gemini-2.5-flash';
        document.getElementById('systemPrompt').value = data.system_prompt || '';
        document.getElementById('aiTone').value = data.ai_tone || 'official_humorous';
        document.getElementById('fallbackMessage').value = data.fallback_message || '';
    } catch (e) {
        console.error(e);
    }
}

async function saveAISettings() {
    const modelSelect = document.getElementById('geminiModelSelect');
    const body = {
        gemini_model: modelSelect ? modelSelect.value : 'gemini-2.5-flash',
        system_prompt: document.getElementById('systemPrompt').value,
        ai_tone: document.getElementById('aiTone').value,
        fallback_message: document.getElementById('fallbackMessage').value
    };
    try {
        const res = await fetch(`${API_BASE}/settings`, {
            method: 'PUT',
            headers: getAuthHeaders(),
            body: JSON.stringify(body)
        });
        if (res.ok) {
            showToast('AI პარამეტრები და მოდელი წარმატებით შეინახა!');
        }
    } catch (e) {
        console.error(e);
    }
}

async function testGeminiConnection() {
    showToast('Gemini-სთან კავშირი მოწმდება...');
    try {
        const res = await fetch(`${API_BASE}/settings/test-gemini`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
        const data = await res.json();
        if (data.status === 'success') {
            alert(`✅ Gemini კავშირი წარმატებულია!\n\nმოდელი: ${data.model}\nპასუხი: ${data.reply}`);
        } else {
            alert(`⚠️ შეცდომა: ${data.message}`);
        }
    } catch (e) {
        alert('კავშირის შეცდომა');
    }
}

// --- 4.1. CHANNEL POSTS (AI CREATOR & SCHEDULER) ---
function previewPostImageUrl(url) {
    const previewBox = document.getElementById('postImagePreviewBox');
    const previewImg = document.getElementById('postImagePreview');
    if (url && url.trim()) {
        if (previewImg) previewImg.src = url.trim();
        if (previewBox) previewBox.style.display = 'block';
    } else {
        if (previewBox) previewBox.style.display = 'none';
    }
}

async function generateChannelPostWithAI() {
    const rawNotes = document.getElementById('postRawNotes').value.trim();
    const photoUrl = document.getElementById('postImageUrl') ? document.getElementById('postImageUrl').value.trim() : '';
    if (!rawNotes) {
        alert('გთხოვთ შეიყვანოთ პროდუქტის მოკლე მონაცემები (Raw Notes)');
        return;
    }

    const btn = document.getElementById('generatePostBtn');
    if (btn) {
        btn.innerText = '⏳ Gemini პოსტს აგენერირებს...';
        btn.disabled = true;
    }

    try {
        const res = await fetch(`${API_BASE}/marketing/posts/generate`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                notes: rawNotes,
                raw_notes: rawNotes,
                photo_url: photoUrl || null
            })
        });
        if (res.ok) {
            const data = await res.json();
            document.getElementById('postGeneratedText').value = data.generated_text || data.generated_post || '';
            showToast('✨ პოსტი წარმატებით დაგენერირდა!');
        } else {
            const err = await res.json();
            alert(err.detail || 'გენერირების შეცდომა');
        }
    } catch (e) {
        console.error('Generate error:', e);
        alert('კავშირის შეცდომა');
    } finally {
        if (btn) {
            btn.innerText = '✨ Gemini AI-ით გენერირება';
            btn.disabled = false;
        }
    }
}

async function publishChannelPostNow() {
    const text = document.getElementById('postGeneratedText').value.trim();
    const photo = document.getElementById('postImageUrl').value.trim();

    if (!text) {
        alert('გთხოვთ შეიყვანოთ ან დააგენერიროთ პოსტის ტექსტი');
        return;
    }

    if (!confirm('ნამდვილად გსურთ ამ პოსტის ახლავე გამოქვეყნება ტელეგრამ ჩანელში (@Geosteamforeveryone)?')) return;

    showToast('პოსტი ქვეყნდება ჩანელში...');
    try {
        const res = await fetch(`${API_BASE}/marketing/posts/publish-now`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ text: text, photo_url: photo || null })
        });
        if (res.ok) {
            showToast('🚀 პოსტი წარმატებით გამოქვეყნდა ჩანელში!');
            document.getElementById('postGeneratedText').value = '';
            document.getElementById('postRawNotes').value = '';
            document.getElementById('postImageUrl').value = '';
            const previewBox = document.getElementById('postImagePreviewBox');
            if (previewBox) previewBox.style.display = 'none';
            loadChannelPosts();
        } else {
            const err = await res.json();
            alert(`შეცდომა: ${err.detail || 'ვერ გამოქვეყნდა'}`);
        }
    } catch (e) {
        console.error('Publish error:', e);
        alert('გამოქვეყნების შეცდომა');
    }
}

async function scheduleChannelPost() {
    const text = document.getElementById('postGeneratedText').value.trim();
    const photo = document.getElementById('postImageUrl').value.trim();
    const schedInput = document.getElementById('postScheduleTime').value;

    if (!text) {
        alert('გთხოვთ შეიყვანოთ ან დააგენერიროთ პოსტის ტექსტი');
        return;
    }
    if (!schedInput) {
        alert('გთხოვთ მიუთითოთ გამოქვეყნების დრო');
        return;
    }

    const schedDate = new Date(schedInput);
    if (isNaN(schedDate.getTime())) {
        alert('გთხოვთ მიუთითოთ ვალიდური დრო');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/marketing/posts/schedule`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                text: text,
                photo_url: photo || null,
                scheduled_for: schedDate.toISOString()
            })
        });
        if (res.ok) {
            showToast('⏰ პოსტი წარმატებით დაიგეგმა!');
            document.getElementById('postGeneratedText').value = '';
            document.getElementById('postRawNotes').value = '';
            document.getElementById('postImageUrl').value = '';
            document.getElementById('postScheduleTime').value = '';
            const previewBox = document.getElementById('postImagePreviewBox');
            if (previewBox) previewBox.style.display = 'none';
            loadChannelPosts();
        } else {
            const err = await res.json();
            alert(err.detail || 'დაგეგმვის შეცდომა');
        }
    } catch (e) {
        console.error('Schedule error:', e);
        alert('დაგეგმვის შეცდომა');
    }
}

async function loadChannelPosts(manual = false) {
    try {
        const res = await fetch(`${API_BASE}/marketing/posts`, { headers: getAuthHeaders() });
        const posts = await res.json();
        const tbody = document.getElementById('channelPostsTableBody');
        if (!tbody) return;

        if (!Array.isArray(posts) || !posts.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color: var(--text-muted); padding: 1.5rem;">პოსტები ჯერ არ არის დაგეგმილი</td></tr>';
            if (manual) showToast('📋 სია ცარიელია');
            return;
        }

        tbody.innerHTML = posts.map(p => {
            let statusBadge = '<span class="badge badge-warning">⏰ დაგეგმილი</span>';
            if (p.status === 'published') {
                statusBadge = '<span class="badge badge-success">✅ გამოქვეყნებული</span>';
            } else if (p.status === 'failed') {
                statusBadge = `<span class="badge badge-danger" title="${escapeHtml(p.error_message || '')}">❌ შეცდომა</span>`;
            }

            const imgUrl = p.image_path || p.image_url;
            const imgHtml = imgUrl
                ? `<br><a href="${imgUrl}" target="_blank" style="font-size:0.75rem; color:var(--primary);">🖼️ ფოტო</a>`
                : '';

            const rawTime = p.scheduled_for || p.published_at || p.created_at;
            const timeStr = rawTime ? new Date(rawTime).toLocaleString('ka-GE') : '-';
            const postContent = p.generated_text || p.post_text || '';
            const shortText = postContent.length > 70 ? postContent.substring(0, 70) + '...' : postContent;

            return `
                <tr>
                    <td>${statusBadge}</td>
                    <td>
                        <small><strong>${escapeHtml(shortText)}</strong>${imgHtml}</small>
                    </td>
                    <td><small style="color:var(--text-secondary)">${timeStr}</small></td>
                    <td>
                        <button class="btn btn-danger btn-sm" style="padding: 2px 6px;" onclick="deleteChannelPost(${p.id})">🗑️</button>
                    </td>
                </tr>
            `;
        }).join('');
        if (manual) showToast('🔄 განრიგი და ისტორია განახლდა');
    } catch (e) {
        console.error('Error loading channel posts:', e);
        if (manual) showToast('❌ განახლების შეცდომა');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.innerText = text;
    return div.innerHTML;
}

async function deleteChannelPost(id) {
    if (!confirm('ნამდვილად გსურთ პოსტის წაშლა?')) return;
    try {
        const res = await fetch(`${API_BASE}/marketing/posts/${id}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });
        if (res.ok) {
            showToast('პოსტი წაიშალა');
            loadChannelPosts();
        }
    } catch (e) {
        console.error(e);
    }
}

// --- 5. MARKETING & BROADCAST ---
async function sendBroadcastMessage() {
    const targetSelect = document.getElementById('broadcastTarget');
    const target = targetSelect ? targetSelect.value : 'all';
    const text = document.getElementById('broadcastText').value.trim();
    const photo = document.getElementById('broadcastPhotoUrl').value.trim();

    if (!text) {
        alert('გთხოვთ შეიყვანოთ შეტყობინების ტექსტი');
        return;
    }

    const targetDesc = target === 'all'
        ? 'ყველა მომხმარებლის პირადში (ბოტის მომხმარებლები + ჩანელის გამომწერები)'
        : (target === 'channel' ? 'მხოლოდ ჩანელის (@Geosteamforeveryone) გამომწერების პირადში' : 'მხოლოდ ბოტის მომხმარებლების პირადში');

    if (!confirm(`ნამდვილად გსურთ მასობრივი შეტყობინების გაგზავნა:\n👉 ${targetDesc}?`)) return;

    showToast('შეტყობინება იგზავნება პირად შეტყობინებებში...');
    try {
        const res = await fetch(`${API_BASE}/marketing/broadcast`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                message: text,
                photo_url: photo || null,
                target: target
            })
        });
        const data = await res.json();
        if (res.ok) {
            alert(`✅ პირადი შეტყობინებების გაგზავნა დასრულდა!\n\n🎯 სამიზნე: ${targetDesc}\n👥 შერჩეული ადრესატები: ${data.total_recipients || 0}\n📬 წარმატებით ჩაბარდა: ${data.sent_successfully || 0}\n❌ ვერ გაიგზავნა/დაბლოკილი: ${data.failed || 0}`);
            showToast(data.message || 'მასობრივი შეტყობინება წარმატებით გაიგზავნა!', 'success');
            document.getElementById('broadcastText').value = '';
        } else {
            alert(`შეცდომა: ${data.detail || 'გაგზავნა ვერ მოხერხდა'}`);
        }
    } catch (e) {
        alert('გაგზავნის შეცდომა: სერვერთან კავშირი შეწყდა');
    }
}

async function loadPromos() {
    try {
        const res = await fetch(`${API_BASE}/marketing/promos`, { headers: getAuthHeaders() });
        const promos = await res.json();
        const tbody = document.getElementById('promoCodesTableBody');
        if (!promos.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color: var(--text-muted);">პრომოკოდები არ არის</td></tr>';
            return;
        }
        tbody.innerHTML = promos.map(p => `
            <tr>
                <td><strong>${p.code}</strong></td>
                <td>${p.discount_percent}%</td>
                <td>${p.times_used} / ${p.usage_limit}</td>
                <td><button class="btn btn-danger btn-sm" onclick="deletePromo(${p.id})">🗑️</button></td>
            </tr>
        `).join('');
    } catch (e) { console.error(e); }
}

async function createPromoCode() {
    const code = document.getElementById('newPromoCode').value.trim();
    const percent = parseFloat(document.getElementById('newPromoPercent').value);
    if (!code || isNaN(percent)) {
        alert('შეიყვანეთ კოდი და პროცენტი');
        return;
    }
    try {
        const res = await fetch(`${API_BASE}/marketing/promos`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ code, discount_percent: percent })
        });
        if (res.ok) {
            document.getElementById('newPromoCode').value = '';
            document.getElementById('newPromoPercent').value = '';
            showToast('პრომოკოდი შეიქმნა');
            loadPromos();
        }
    } catch (e) { console.error(e); }
}

async function deletePromo(id) {
    try {
        const res = await fetch(`${API_BASE}/marketing/promos/${id}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });
        if (res.ok) {
            showToast('პრომოკოდი წაიშალა');
            loadPromos();
        }
    } catch (e) { console.error(e); }
}

// --- 6. STORE SETTINGS & LOGISTICS ---
let isIbanMasked = true;

async function loadStoreSettings() {
    try {
        const res = await fetch(`${API_BASE}/settings`, { headers: getAuthHeaders() });
        const s = await res.json();
        if (document.getElementById('deliveryCourierEnabled')) document.getElementById('deliveryCourierEnabled').checked = s.delivery_courier_enabled;
        if (document.getElementById('deliveryPickupEnabled')) document.getElementById('deliveryPickupEnabled').checked = s.delivery_pickup_enabled;
        if (document.getElementById('deliveryMailEnabled')) document.getElementById('deliveryMailEnabled').checked = s.delivery_mail_enabled;
        
        if (document.getElementById('deliveryRegionsCenterFee')) document.getElementById('deliveryRegionsCenterFee').value = s.delivery_regions_center_fee || 9.0;
        if (document.getElementById('deliveryRegionsVillageFee')) document.getElementById('deliveryRegionsVillageFee').value = s.delivery_regions_village_fee || 12.0;
        if (document.getElementById('deliveryRegionsDurationDays')) document.getElementById('deliveryRegionsDurationDays').value = s.delivery_regions_duration_days || 3;

        document.getElementById('pickupAddress').value = s.pickup_address || '';
        document.getElementById('pickupLat').value = s.pickup_lat || '';
        document.getElementById('pickupLng').value = s.pickup_lng || '';

        document.getElementById('paymentCashEnabled').checked = s.payment_cash_enabled;
        document.getElementById('paymentBankEnabled').checked = s.payment_bank_enabled;
        document.getElementById('bankName').value = s.bank_name || '';
        
        const ibanInput = document.getElementById('bankIban');
        if (ibanInput) {
            ibanInput.value = s.bank_iban || '';
            ibanInput.type = isIbanMasked ? 'password' : 'text';
        }
        document.getElementById('bankRecipient').value = s.bank_recipient || '';

        document.getElementById('adminTelegramIds').value = s.admin_telegram_ids || '';
        document.getElementById('adminEmail').value = s.admin_email || '';

        if (document.getElementById('smtpHost')) document.getElementById('smtpHost').value = s.smtp_host || '';
        if (document.getElementById('smtpPort')) document.getElementById('smtpPort').value = s.smtp_port || 587;
        if (document.getElementById('smtpUser')) document.getElementById('smtpUser').value = s.smtp_user || '';
        if (document.getElementById('smtpPassword')) document.getElementById('smtpPassword').value = s.smtp_password || '';
        if (document.getElementById('autoBackupEnabled')) document.getElementById('autoBackupEnabled').checked = (s.auto_backup_enabled !== false);

        loadSecurityLogs();
    } catch (e) { console.error(e); }
}

function toggleIbanVisibility() {
    const ibanInput = document.getElementById('bankIban');
    if (!ibanInput) return;
    isIbanMasked = !isIbanMasked;
    ibanInput.type = isIbanMasked ? 'password' : 'text';
}

async function loadSecurityLogs() {
    const tbody = document.getElementById('securityLogsTableBody');
    if (!tbody) return;
    try {
        const res = await fetch(`${API_BASE}/settings/security-logs`, { headers: getAuthHeaders() });
        const data = await res.json();
        const logs = data.logs || [];
        if (!logs.length) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted); padding: 12px;">🛡️ ცვლილებები ჯერ არ დაფიქსირებულა (სისტემა დაცულია)</td></tr>';
            return;
        }
        tbody.innerHTML = logs.map(l => `
            <tr>
                <td><small style="color:var(--text-secondary)">${escapeHtml(l.timestamp || '')}</small></td>
                <td><strong>${escapeHtml(l.user || 'Admin')}</strong></td>
                <td><span style="color:var(--primary); font-weight:600;">${escapeHtml(l.action || '')}</span></td>
                <td><small>${escapeHtml(l.details || '')}</small></td>
                <td><span class="badge badge-success">${escapeHtml(l.status || 'დაცულია')}</span></td>
            </tr>
        `).join('');
    } catch (e) {
        console.error('Error loading security logs:', e);
    }
}

async function saveStoreSettings() {
    const body = {
        delivery_courier_enabled: document.getElementById('deliveryCourierEnabled').checked,
        delivery_pickup_enabled: document.getElementById('deliveryPickupEnabled').checked,
        delivery_mail_enabled: document.getElementById('deliveryMailEnabled').checked,
        delivery_regions_center_fee: parseFloat(document.getElementById('deliveryRegionsCenterFee').value) || 9.0,
        delivery_regions_village_fee: parseFloat(document.getElementById('deliveryRegionsVillageFee').value) || 12.0,
        delivery_regions_duration_days: parseInt(document.getElementById('deliveryRegionsDurationDays').value) || 3,
        pickup_address: document.getElementById('pickupAddress').value.trim(),
        pickup_lat: parseFloat(document.getElementById('pickupLat').value) || 41.6938,
        pickup_lng: parseFloat(document.getElementById('pickupLng').value) || 44.8015,
        payment_cash_enabled: document.getElementById('paymentCashEnabled').checked,
        payment_bank_enabled: document.getElementById('paymentBankEnabled').checked,
        bank_name: document.getElementById('bankName').value.trim(),
        bank_iban: document.getElementById('bankIban').value.trim(),
        bank_recipient: document.getElementById('bankRecipient').value.trim(),
        admin_telegram_ids: document.getElementById('adminTelegramIds').value.trim(),
        admin_email: document.getElementById('adminEmail').value.trim(),
        smtp_host: document.getElementById('smtpHost') ? document.getElementById('smtpHost').value.trim() : null,
        smtp_port: document.getElementById('smtpPort') ? parseInt(document.getElementById('smtpPort').value) || 587 : 587,
        smtp_user: document.getElementById('smtpUser') ? document.getElementById('smtpUser').value.trim() : null,
        smtp_password: document.getElementById('smtpPassword') ? document.getElementById('smtpPassword').value.trim() : null,
        auto_backup_enabled: document.getElementById('autoBackupEnabled') ? document.getElementById('autoBackupEnabled').checked : true
    };
    try {
        const res = await fetch(`${API_BASE}/settings`, {
            method: 'PUT',
            headers: getAuthHeaders(),
            body: JSON.stringify(body)
        });
        if (res.ok) {
            showToast('✅ მაღაზიის პარამეტრები და ლოჯისტიკა წარმატებით შეინახა');
            loadSecurityLogs();
        } else {
            const err = await res.json();
            alert(`შეცდომა: ${err.detail || 'ვერ შეინახა'}`);
        }
    } catch (e) { console.error(e); }
}

async function testEmailConnection() {
    showToast('📧 იგზავნება სატესტო იმეილი...');
    try {
        const res = await fetch(`${API_BASE}/settings/test-email`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
        const data = await res.json();
        if (data.status === 'success') {
            alert(`✅ ${data.message}`);
        } else {
            alert(`❌ ${data.message}`);
        }
    } catch (e) {
        console.error(e);
        alert('❌ სერვერთან კავშირის შეცდომა');
    }
}

// --- MARKETING CAMPAIGN PRESETS & AI ENHANCEMENT ---
const PROMO_PRESETS = {
    flash_sale: {
        title: "🔥 FLASH SALE (-20%)",
        text: "🔥 **FLASH SALE: -20% ყველა სითხეზე!**\n\nმხოლოდ მომდევნო 24 საათის განმავლობაში, შეიძინეთ ნებისმიერი 2 ან მეტი სითხე და მიიღეთ 20%-იანი მომენტალური ფასდაკლება! 💨\n\n🛵 თბილისში მიწოდება Yandex საკურიეროთი (სწრაფად მისამართზე)\n📦 რეგიონებში მიწოდება (ცენტრი 9₾, სოფელი 12₾ - 3 დღეში)\n🏬 თვითგატანა მაღაზიიდან - უფასო\n\n👉 შეუკვეთეთ ბოტში ღილაკით: 🛒 შეკვეთა"
    },
    combo_deal: {
        title: "🎁 SUPER COMBO DEAL",
        text: "🎁 **SUPER VAPE COMBO: 1+1 შეთავაზება!**\n\nშეიძინეთ 2 პრემიუმ სითხე (Elfliq / Chaser / Asian Bomb) და მიიღეთ მე-3 სითხე ან ქოილი საჩუქრად! 🎁\n\nარომატების მრავალფეროვანი არჩევანი და უმაღლესი ხარისხი.\n\n👉 დასაჯავშნად მოგვწერეთ პირდაპირ ბოტში!"
    },
    free_delivery: {
        title: "🚚 უფასო მიწოდება",
        text: "🚚 **უფასო მიწოდების აქცია Geosteam-ში!**\n\n45 ლარზე მეტი შეკვეთის შემთხვევაში — მიწოდება სრულიად უფასოა როგორც თბილისში (Yandex საკურიერო), ასევე საქართველოს ნებისმიერ რეგიონსა და სოფელში! 🚀\n\n👉 გამოიყენეთ შანსი და შეუკვეთეთ თქვენი საყვარელი გემოები!"
    },
    new_drop: {
        title: "🫐 NEW FLAVORS DROP",
        text: "🫐 **NEW FLAVOR DROP — ახალი არომატები უკვე მარაგშია!**\n\nგაყიდვაშია ყველაზე მოთხოვნადი Elfliq, Chaser & Asian Bomb-ის ახალი კენკროვანი, ტროპიკული და ყინულიანი არომატები! ❄️💨\n\nმარაგი შეზღუდულია, იჩქარეთ!\n👉 იხილეთ სრული ასორტიმენტი კატალოგში."
    },
    vip_code: {
        title: "👑 VIP PROMO DROP",
        text: "👑 **VIP EXCLUSIVE: გამოიყენეთ პრომოკოდი GEOVIP!**\n\nჩვენი გამომწერებისთვის მოქმედებს ექსკლუზიური 10%-იანი ფასდაკლება პრომოკოდით: **GEOVIP** 🎟️\n\nჩაწერეთ კოდი შეკვეთის გაფორმებისას და მიიღეთ საუკეთესო ფასი!\n👉 შეკვეთისთვის დააჭირეთ: 🛒 შეკვეთა"
    },
    weekend_sale: {
        title: "💨 WEEKEND CLOUDS",
        text: "💨 **WEEKEND CLOUDS: შაბათ-კვირის სპეციალური ფასი!**\n\nამ შაბათ-კვირას ყველა 30ml პრემიუმ სითხე განსაკუთრებულ ფასად — მხოლოდ 22 ლარად! 🔥\n\nდაისვენეთ საუკეთესო გემოებთან ერთად.\n👉 შეუკვეთეთ ახლავე ბოტში!"
    }
};

async function applyPromoPreset(presetKey, useAI = false) {
    const preset = PROMO_PRESETS[presetKey];
    if (!preset) return;

    const bText = document.getElementById('broadcastText');
    if (!bText) return;

    if (!useAI) {
        bText.value = preset.text;
        showToast(`📝 შაბლონი ჩაისვა: ${preset.title}`);
        bText.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
    }

    // AI Generation
    showToast(`✨ Gemini AI არგებს აქციას: ${preset.title}...`);
    try {
        const res = await fetch(`${API_BASE}/marketing/posts/generate`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ raw_notes: `მოამზადე მიმზიდველი Telegram Broadcast სარეკლამო მესიჯი აქციისთვის: ${preset.title}.\nძირითადი დეტალები: ${preset.text}` })
        });
        const data = await res.json();
        if (data.generated_text) {
            bText.value = data.generated_text;
            showToast('✨ აქცია წარმატებით გალამაზდა Gemini AI-ით!');
            bText.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } else {
            bText.value = preset.text;
            showToast('📝 შაბლონი ჩაისვა');
        }
    } catch (e) {
        bText.value = preset.text;
        showToast('📝 შაბლონი ჩაისვა');
    }
}

async function enhanceBroadcastWithAI() {
    const bText = document.getElementById('broadcastText');
    if (!bText || !bText.value.trim()) {
        alert('გთხოვთ ჯერ ჩაწეროთ მოკლე ტექსტი ან აირჩიოთ აქციის შაბლონი');
        return;
    }
    showToast('✨ Gemini AI ალამაზებს Broadcast ტექსტს...');
    try {
        const res = await fetch(`${API_BASE}/marketing/posts/generate`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ raw_notes: `გააუმჯობესე და გახადე მაქსიმალურად გაყიდვადი შემდეგი Telegram შეტყობინება: ${bText.value.trim()}` })
        });
        const data = await res.json();
        if (data.generated_text) {
            bText.value = data.generated_text;
            showToast('✨ ტექსტი წარმატებით გალამაზდა!');
        }
    } catch (e) {
        console.error(e);
        alert('AI გენერაციის შეცდომა');
    }
}

// --- MOBILE ACCESS & TELEGRAM MINI APP MODAL ---
async function openMobileAccessModal() {
    const modal = document.getElementById('mobileAccessModal');
    if (!modal) return;
    modal.style.display = 'flex';

    try {
        const res = await fetch(`${API_BASE}/settings/mobile-info`, { headers: getAuthHeaders() });
        const data = await res.json();
        const mobileUrl = data.mobile_url || window.location.origin + '/admin';
        
        const input = document.getElementById('mobileAccessUrlInput');
        if (input) input.value = mobileUrl;

        const qrImg = document.getElementById('mobileQrCodeImg');
        if (qrImg) {
            qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(mobileUrl)}`;
        }
    } catch (e) {
        console.error('Error getting mobile info:', e);
    }
}

function closeMobileAccessModal() {
    const modal = document.getElementById('mobileAccessModal');
    if (modal) modal.style.display = 'none';
}

function copyMobileUrl() {
    const input = document.getElementById('mobileAccessUrlInput');
    if (!input) return;
    navigator.clipboard.writeText(input.value).then(() => {
        showToast('📋 ბმული დაკოპირდა ბუფერში!');
    }).catch(() => {
        input.select();
        document.execCommand('copy');
        showToast('📋 ბმული დაკოპირდა!');
    });
}

// Init events
document.addEventListener('DOMContentLoaded', () => {
    if (!checkAuth()) return;

    // Nav click handlers
    document.querySelectorAll('.nav-item').forEach(el => {
        el.addEventListener('click', () => switchTab(el.getAttribute('data-tab')));
    });

    // Quick new product button
    document.getElementById('quickNewProductBtn').addEventListener('click', () => openProductModal());

    // Logout
    document.getElementById('logoutBtn').addEventListener('click', () => {
        localStorage.clear();
        window.location.href = '/login';
    });

    // Initial load
    switchTab('dashboard');
});

// ==========================================================================
// ADMIN AI COPILOT CONTROLLER (Gemini 3.8 Flash Operations Assistant)
// ==========================================================================

let isCopilotOpen = false;

function toggleAdminCopilot() {
    const win = document.getElementById('adminCopilotWindow');
    if (!win) return;

    isCopilotOpen = !isCopilotOpen;
    win.style.display = isCopilotOpen ? 'flex' : 'none';

    if (isCopilotOpen) {
        loadCopilotHistory();
        const input = document.getElementById('copilotUserInput');
        if (input) setTimeout(() => input.focus(), 150);
    }
}

function handleCopilotKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendCopilotMessage();
    }
}

function quickCopilotPrompt(text) {
    const input = document.getElementById('copilotUserInput');
    if (input) {
        input.value = text;
        sendCopilotMessage();
    }
}

async function loadCopilotHistory() {
    const box = document.getElementById('copilotMessagesBox');
    if (!box) return;

    try {
        const res = await fetch(`${API_BASE}/admin/assistant/history`, {
            headers: getAuthHeaders()
        });
        if (!res.ok) return;
        const messages = await res.json();
        if (!messages.length) return;

        box.innerHTML = '';
        messages.forEach(m => {
            appendCopilotBubble(m.sender, m.text, m.actions, m.timestamp);
        });
        scrollCopilotBottom();
    } catch (e) {
        console.error('Error loading copilot history:', e);
    }
}

async function sendCopilotMessage() {
    const input = document.getElementById('copilotUserInput');
    const sendBtn = document.getElementById('copilotSendBtn');
    const msg = input.value.trim();
    if (!msg) return;

    input.value = '';
    input.disabled = true;
    if (sendBtn) sendBtn.disabled = true;

    // Append user bubble
    appendCopilotBubble('admin', msg, [], new Date().toISOString());
    scrollCopilotBottom();

    // Append typing indicator
    const box = document.getElementById('copilotMessagesBox');
    const typingId = 'copilot-typing-' + Date.now();
    const typingEl = document.createElement('div');
    typingEl.id = typingId;
    typingEl.className = 'copilot-msg copilot-msg-assistant';
    typingEl.innerHTML = `
        <div class="copilot-msg-header">🤖 Geosteam Copilot</div>
        <div style="display:flex; align-items:center; gap:6px; color:#a5b4fc;">
            <span>ფიქრობს და ამუშავებს მონაცემებს...</span>
        </div>
    `;
    box.appendChild(typingEl);
    scrollCopilotBottom();

    try {
        const res = await fetch(`${API_BASE}/admin/assistant/chat`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ message: msg })
        });

        const data = await res.json();
        typingEl.remove();

        if (res.ok) {
            appendCopilotBubble('assistant', data.reply, data.actions, data.timestamp);

            // Execute Copilot UI and Data Actions in Real-Time!
            if (data.actions && data.actions.length > 0) {
                data.actions.forEach(act => {
                    executeCopilotUIAction(act);
                });

                const hasProdChange = data.actions.some(a => ['update_product', 'add_new_product'].includes(a.tool));
                const hasOrderChange = data.actions.some(a => ['update_order_status'].includes(a.tool));
                const hasSettingsChange = data.actions.some(a => ['update_store_settings'].includes(a.tool));

                if (hasProdChange) {
                    loadProducts();
                    loadDashboard();
                }
                if (hasOrderChange) {
                    loadOrders();
                    loadDashboard();
                }
                if (hasSettingsChange) {
                    loadSettings();
                    loadAISettings();
                }
            }
        } else {
            appendCopilotBubble('assistant', `⚠️ შეცდომა: ${data.detail || 'მოთხოვნის დამუშავება ვერ მოხერხდა'}`, [], new Date().toISOString());
        }
    } catch (err) {
        if (typingEl) typingEl.remove();
        appendCopilotBubble('assistant', `⚠️ კავშირის შეცდომა: ${err.message}`, [], new Date().toISOString());
    } finally {
        input.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
        input.focus();
        scrollCopilotBottom();
    }
}

function executeCopilotUIAction(act) {
    if (!act || !act.tool) return;
    const tool = act.tool;
    const args = act.args || {};

    if (tool === 'navigate_to_tab') {
        const tab = args.tab_name || act.result?.tab || args.tab;
        if (tab && typeof showTab === 'function') {
            showTab(tab);
            const tabEl = document.getElementById(tab);
            if (tabEl) {
                tabEl.classList.add('copilot-glow-field');
                setTimeout(() => tabEl.classList.remove('copilot-glow-field'), 2500);
            }
        }
    } else if (tool === 'fill_form_field') {
        const fieldName = (args.field_name || args.field || '').trim();
        const val = args.value;
        if (fieldName && val !== undefined) {
            let el = document.getElementById(fieldName) || document.querySelector(`[name="${fieldName}"]`);
            if (!el) {
                const fieldMap = {
                    "notes": "postRawNotes",
                    "raw_notes": "postRawNotes",
                    "post_text": "postGeneratedText",
                    "generated_text": "postGeneratedText",
                    "photo_url": "postImageUrl",
                    "image_url": "postImageUrl",
                    "pickup_address": "settingPickupAddress",
                    "bank_name": "settingBankName",
                    "bank_iban": "settingBankIban",
                    "bank_recipient": "settingBankRecipient",
                    "system_prompt": "settingSystemPrompt",
                    "fallback_message": "settingFallbackMessage",
                    "admin_telegram_ids": "settingAdminIds",
                    "delivery_price_tbilisi": "settingDeliveryTbilisi",
                    "delivery_price_regions": "settingDeliveryRegions",
                    "product_name": "prodName",
                    "product_brand": "prodBrand",
                    "product_price": "prodPrice",
                    "product_stock": "prodStock"
                };
                const mappedId = fieldMap[fieldName.toLowerCase()];
                if (mappedId) el = document.getElementById(mappedId);
            }
            if (el) {
                el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                el.classList.add('copilot-glow-field');
                setTimeout(() => el.classList.remove('copilot-glow-field'), 3000);
            }
        }
    } else if (tool === 'open_modal') {
        const modalName = args.modal_name || args.modal;
        if (modalName === 'productModal' || modalName === 'add_product') {
            if (typeof openProductModal === 'function') openProductModal();
        } else if (modalName === 'receiptModal') {
            const modal = document.getElementById('receiptModal');
            if (modal) modal.style.display = 'flex';
        }
    } else if (tool === 'update_store_settings') {
        if (typeof showTab === 'function') showTab('settings');
        if (typeof loadSettings === 'function') loadSettings();
    }
}

function appendCopilotBubble(sender, text, actions = [], timestamp = null) {
    const box = document.getElementById('copilotMessagesBox');
    if (!box) return;

    const bubble = document.createElement('div');
    bubble.className = `copilot-msg copilot-msg-${sender === 'admin' ? 'user' : 'assistant'}`;

    const senderHeader = sender === 'admin'
        ? `<div class="copilot-msg-header" style="color:#ffffff;">👤 თქვენ (ადმინისტრატორი)</div>`
        : `<div class="copilot-msg-header">🤖 Geosteam Admin Copilot</div>`;

    let actionsHtml = '';
    if (actions && actions.length > 0) {
        actionsHtml = actions.map(act => {
            const toolName = act.tool || 'action';
            let label = `⚡ ${toolName}`;
            if (toolName === 'navigate_to_tab') label = `🧭 გადასვლა ჩანართზე: ${act.args?.tab_name || ''}`;
            else if (toolName === 'fill_form_field') label = `✍️ ველის შევსება: ${act.args?.field_name || ''} = "${(act.args?.value || '').toString().slice(0, 30)}..."`;
            else if (toolName === 'open_modal') label = `🪟 ფანჯრის გახსნა: ${act.args?.modal_name || ''}`;
            else if (toolName === 'update_store_settings') label = `⚙️ მაღაზიის პარამეტრები განახლდა`;
            else if (toolName === 'update_product') label = `✅ პროდუქტი განახლდა: ID #${act.args?.product_id || ''}`;
            else if (toolName === 'add_new_product') label = `🎉 დაემატა ახალი პროდუქტი: ${act.args?.name || ''}`;
            else if (toolName === 'update_order_status') label = `📦 შეკვეთის სტატუსი: #${act.args?.order_identifier || ''} -> ${act.args?.new_status || ''}`;
            else if (toolName === 'schedule_channel_post') label = `📢 პოსტი დაიგეგმა ჩანელში`;
            else if (toolName === 'get_store_metrics') label = `📊 ანალიტიკა მიღებულია`;
            return `<div class="copilot-action-card">${label}</div>`;
        }).join('');
    }

    const timeStr = timestamp ? new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
    const formattedText = text.replace(/\n/g, '<br>');

    bubble.innerHTML = `
        ${senderHeader}
        <div>${formattedText}</div>
        ${actionsHtml}
        <div class="copilot-time">${timeStr}</div>
    `;

    box.appendChild(bubble);
}

function scrollCopilotBottom() {
    const box = document.getElementById('copilotMessagesBox');
    if (box) box.scrollTop = box.scrollHeight;
}

async function clearCopilotHistory() {
    if (!confirm('ნამდვილად გსურთ ასისტენტის საუბრის ისტორიის გასუფთავება?')) return;
    try {
        const res = await fetch(`${API_BASE}/admin/assistant/history`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });
        if (res.ok) {
            const box = document.getElementById('copilotMessagesBox');
            if (box) {
                box.innerHTML = `
                    <div class="copilot-msg copilot-msg-assistant">
                        <div class="copilot-msg-header">🤖 Geosteam Admin Copilot</div>
                        <div class="copilot-msg-content">
                            ისტორია გასუფთავებულია! ✨ რით შემიძლია დაგეხმაროთ?
                        </div>
                    </div>
                `;
            }
            showToast('ასისტენტის ისტორია გასუფთავდა');
        }
    } catch (e) {
        console.error(e);
    }
}

// --- 8. BLACKLIST (შავი სია & AI Vision Anti-Fraud) ---
async function loadBlacklist() {
    try {
        const res = await fetch(`${API_BASE}/blacklist`, { headers: getAuthHeaders() });
        if (res.status === 401) {
            window.location.href = '/login';
            return;
        }
        const list = await res.json();
        const tbody = document.getElementById('blacklistTableBody');
        const badge = document.getElementById('blacklistBadge');

        if (badge) {
            if (list.length > 0) {
                badge.style.display = 'inline-block';
                badge.innerText = list.length;
            } else {
                badge.style.display = 'none';
            }
        }

        if (!tbody) return;

        if (!list || !list.length) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" style="text-align:center; padding: 2rem; color: var(--text-muted);">
                        🛡️ შავი სია ცარიელია. ყველა მომხმარებლის ქვითარი და ტრანზაქცია ვალიდურია!
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = list.map(item => {
            const dateStr = item.created_at ? new Date(item.created_at).toLocaleString('ka-GE') : '-';
            const receiptBtn = item.receipt_url
                ? `<a href="${item.receipt_url}" target="_blank" class="btn btn-secondary btn-sm" style="font-size:0.75rem;">🧾 ქვითრის ნახვა</a>`
                : '<span style="color:var(--text-muted); font-size:0.8rem;">-</span>';
            const usernameDisplay = item.username ? `@${item.username.replace('@', '')}` : (item.full_name || `ID ${item.telegram_id}`);

            return `
                <tr>
                    <td>#${item.id}</td>
                    <td><code>${item.telegram_id}</code></td>
                    <td><strong>${usernameDisplay}</strong></td>
                    <td><span class="badge badge-blacklist">${item.reason}</span></td>
                    <td>${receiptBtn}</td>
                    <td style="font-size: 0.82rem; color: var(--text-muted);">${dateStr}</td>
                    <td>
                        <button class="btn btn-secondary btn-sm" style="color:#4ade80; border-color:rgba(74,222,128,0.3);" onclick="removeFromBlacklist(${item.id})" title="ბლოკის მოხსნა">
                            ✓ განბლოკვა
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('Error loading blacklist:', err);
    }
}

function openAddBlacklistModal() {
    const modal = document.getElementById('addBlacklistModal');
    if (modal) {
        document.getElementById('blTelegramId').value = '';
        document.getElementById('blUsername').value = '';
        document.getElementById('blReason').value = '';
        modal.style.display = 'flex';
    }
}

function closeAddBlacklistModal() {
    const modal = document.getElementById('addBlacklistModal');
    if (modal) modal.style.display = 'none';
}

async function submitAddBlacklist() {
    const tgId = document.getElementById('blTelegramId').value.trim();
    const username = document.getElementById('blUsername').value.trim();
    const reason = document.getElementById('blReason').value.trim();

    if (!tgId) {
        showToast('გთხოვთ მიუთითოთ Telegram ID', 'error');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/blacklist`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                telegram_id: parseInt(tgId),
                username: username,
                full_name: username || `User ${tgId}`,
                reason: reason || 'ადმინისტრატორის მიერ დაბლოკილი'
            })
        });

        if (res.ok) {
            showToast('მომხმარებელი წარმატებით დაემატა შავ სიაში', 'success');
            closeAddBlacklistModal();
            loadBlacklist();
        } else {
            const err = await res.json();
            showToast(err.detail || 'შეცდომა შავ სიაში დამატებისას', 'error');
        }
    } catch (e) {
        console.error(e);
        showToast('სერვერთან კავშირის შეცდომა', 'error');
    }
}

async function removeFromBlacklist(blacklistId) {
    if (!confirm('ნამდვილად გსურთ მომხმარებლის განბლოკვა და შავი სიიდან ამოშლა?')) return;

    try {
        const res = await fetch(`${API_BASE}/blacklist/${blacklistId}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });

        if (res.ok) {
            showToast('მომხმარებელი წარმატებით განბლოკილია!', 'success');
            loadBlacklist();
        } else {
            const err = await res.json();
            showToast(err.detail || 'შეცდომა განბლოკვისას', 'error');
        }
    } catch (e) {
        console.error(e);
        showToast('სერვერთან კავშირის შეცდომა', 'error');
    }
}


