import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, func
from backend.app.database import get_db
from backend.app.models import Order, Product, ChatMessage, Customer, AdminUser
from backend.app.services.auth_service import get_current_user
from backend.app.services.notifications import ws_manager

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

class ResetMetricRequest(BaseModel):
    metric: str # "revenue", "orders", "products", "chats", "all"

@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Returns top-level dashboard metrics and recent orders."""
    # 1. Total revenue & orders count
    orders_res = await db.execute(select(Order))
    orders = orders_res.scalars().all()
    
    total_revenue = sum(
        o.total_amount or 0.0 
        for o in orders 
        if (o.payment_status == "paid" or o.order_status in ["delivered", "processing", "COMPLETED", "PAID"])
    )
    total_orders = len(orders)
    
    # 2. Active products
    prods_res = await db.execute(select(Product).where(Product.is_active == True))
    active_prods = prods_res.scalars().all()
    active_products_count = len(active_prods)
    
    # 3. Total customers
    cust_res = await db.execute(select(Customer))
    customers = cust_res.scalars().all()
    total_customers = len(customers)

    # 4. Recent orders (latest 10)
    recent_res = await db.execute(select(Order).order_by(Order.id.desc()).limit(10))
    recent_orders = recent_res.scalars().all()
    
    recent_list = []
    for o in recent_orders:
        recent_list.append({
            "id": o.id,
            "customer_id": o.customer_id,
            "total_amount": o.total_amount,
            "delivery_method": o.delivery_method,
            "delivery_address": o.delivery_address,
            "payment_method": o.payment_method,
            "payment_status": o.payment_status,
            "order_status": o.order_status,
            "receipt_image_url": getattr(o, "receipt_image_url", ""),
            "created_at": o.created_at.isoformat() if o.created_at else None
        })

    return {
        "total_revenue": round(total_revenue, 2),
        "total_orders": total_orders,
        "active_products": active_products_count,
        "total_customers": total_customers,
        "recent_orders": recent_list
    }

@router.get("/analytics")
async def get_dashboard_analytics(
    days: int = 14,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """
    Returns aggregated analytics for visual charts:
    - Daily revenue & order count (last N days)
    - Top selling products / flavors
    - Order status distribution
    - Customer growth & repeat rate
    - Financial summaries (today, week, month, AOV)
    """
    now = datetime.utcnow()
    start_date = now - timedelta(days=days)

    # 1. Fetch all orders
    orders_res = await db.execute(select(Order).order_by(Order.created_at.asc()))
    orders = orders_res.scalars().all()

    # 2. Daily revenue & volume aggregation
    daily_map: Dict[str, Dict[str, Any]] = {}
    for i in range(days):
        d_str = (start_date + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        daily_map[d_str] = {"date": d_str, "revenue": 0.0, "orders_count": 0}

    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    today_rev = 0.0
    week_rev = 0.0
    month_rev = 0.0
    paid_orders_count = 0
    total_paid_revenue = 0.0

    product_sales_map: Dict[str, Dict[str, Any]] = {}
    status_counts: Dict[str, int] = {"new": 0, "processing": 0, "delivered": 0, "cancelled": 0}

    for o in orders:
        o_date_str = o.created_at.strftime("%Y-%m-%d") if o.created_at else today_str
        is_paid_or_completed = (o.payment_status == "paid" or o.order_status in ["delivered", "processing", "COMPLETED", "PAID"])
        amount = float(o.total_amount or 0.0)

        # Status count
        st_key = (o.order_status or "new").lower()
        if st_key in status_counts:
            status_counts[st_key] += 1
        else:
            status_counts[st_key] = 1

        if is_paid_or_completed:
            paid_orders_count += 1
            total_paid_revenue += amount

            # Daily mapping
            if o_date_str in daily_map:
                daily_map[o_date_str]["revenue"] += amount
                daily_map[o_date_str]["orders_count"] += 1

            # Financial periods
            if o.created_at:
                if o_date_str == today_str:
                    today_rev += amount
                if o.created_at >= week_start:
                    week_rev += amount
                if o.created_at >= month_start:
                    month_rev += amount

            # Product level parsing
            try:
                items = json.loads(o.items_json or "[]")
                for it in items:
                    p_name = it.get("product_name") or it.get("name") or "უცნობი სითხე"
                    qty = int(it.get("quantity") or 1)
                    item_price = float(it.get("price") or 33.0)
                    line_total = item_price * qty

                    if p_name not in product_sales_map:
                        product_sales_map[p_name] = {
                            "name": p_name,
                            "sales_count": 0,
                            "revenue": 0.0
                        }
                    product_sales_map[p_name]["sales_count"] += qty
                    product_sales_map[p_name]["revenue"] += line_total
            except Exception:
                pass

    # 3. Top selling products
    sorted_products = sorted(product_sales_map.values(), key=lambda x: x["sales_count"], reverse=True)
    total_units_sold = sum(p["sales_count"] for p in sorted_products) or 1
    for p in sorted_products:
        p["percentage"] = round((p["sales_count"] / total_units_sold) * 100, 1)
        p["revenue"] = round(p["revenue"], 2)

    top_products = sorted_products[:8]

    # If product_sales_map is empty, seed with active catalog for preview
    if not top_products:
        prods_res = await db.execute(select(Product).where(Product.is_active == True).limit(5))
        for p in prods_res.scalars().all():
            top_products.append({
                "name": p.name,
                "sales_count": 0,
                "revenue": 0.0,
                "percentage": 0.0
            })

    # 4. Customer analytics
    cust_res = await db.execute(select(Customer))
    all_cust = cust_res.scalars().all()
    total_customers = len(all_cust)
    new_customers_week = sum(1 for c in all_cust if c.created_at and c.created_at >= week_start)
    
    # Customer order frequency
    cust_order_counts: Dict[int, int] = {}
    for o in orders:
        if o.customer_id:
            cust_order_counts[o.customer_id] = cust_order_counts.get(o.customer_id, 0) + 1
    
    repeat_customers = sum(1 for cid, cnt in cust_order_counts.items() if cnt > 1)
    repeat_rate = round((repeat_customers / max(total_customers, 1)) * 100, 1)

    # 5. Summary metrics
    avg_order_value = round(total_paid_revenue / max(paid_orders_count, 1), 2)

    return {
        "daily_trends": list(daily_map.values()),
        "top_products": top_products,
        "status_distribution": status_counts,
        "customer_metrics": {
            "total_customers": total_customers,
            "new_this_week": new_customers_week,
            "repeat_customers": repeat_customers,
            "repeat_rate_percent": repeat_rate
        },
        "financial_summary": {
            "today_revenue": round(today_rev, 2),
            "week_revenue": round(week_rev, 2),
            "month_revenue": round(month_rev, 2),
            "total_revenue": round(total_paid_revenue, 2),
            "avg_order_value": avg_order_value
        }
    }

@router.post("/reset-metric")
async def reset_metric(
    payload: ResetMetricRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    metric = payload.metric.strip().lower()
    
    if metric in ["revenue", "orders"]:
        # Delete orders or reset
        await db.execute(delete(Order))
        await db.commit()
        msg = "შეკვეთები და შემოსავალი წარმატებით განულდა"
    elif metric == "products":
        # Reset products to inactive or 0 stock
        await db.execute(update(Product).values(is_active=False, stock_quantity=0))
        await db.commit()
        msg = "აქტიური პროდუქტები წარმატებით განულდა"
    elif metric == "chats":
        # Delete chat messages and unpause customers
        await db.execute(delete(ChatMessage))
        await db.execute(update(Customer).values(bot_paused=False, order_state="IDLE", temp_cart="{}"))
        await db.commit()
        msg = "მომხმარებელთა ჩატები წარმატებით განულდა"
    elif metric == "all":
        await db.execute(delete(Order))
        await db.execute(delete(ChatMessage))
        await db.execute(update(Product).values(is_active=False, stock_quantity=0))
        await db.execute(update(Customer).values(bot_paused=False, order_state="IDLE", temp_cart="{}"))
        await db.commit()
        msg = "ყველა მეტრიკა წარმატებით განულდა"
    else:
        raise HTTPException(status_code=400, detail="არასწორი მეტრიკის ტიპი")

    await ws_manager.broadcast({
        "type": "dashboard_reset",
        "metric": metric
    })

    return {"success": True, "message": msg}

