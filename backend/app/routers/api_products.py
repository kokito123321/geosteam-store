import json
import logging
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from backend.app.database import get_db
from backend.app.models import Product, AdminUser
from backend.app.schemas import ProductCreate, ProductUpdate, ProductResponse, BulkDeleteProductsRequest
from backend.app.services.auth_service import get_current_user
from backend.app.services.notifications import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/products", tags=["products"])

async def auto_sync_seed_products(db: AsyncSession):
    """Automatically persists current product catalog into seed_products.json for safe restart recovery."""
    try:
        res = await db.execute(select(Product).order_by(Product.id.asc()))
        products = res.scalars().all()
        seed_file = Path(__file__).resolve().parent.parent / "seed_products.json"
        data = [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description or "",
                "price": float(p.price or 0.0),
                "volume_ml": p.volume_ml or 30,
                "color_type": p.color_type or "",
                "stock_quantity": int(p.stock_quantity or 0),
                "is_active": int(1 if p.is_active else 0),
                "photo_url": p.photo_url or "",
                "channel_post_url": p.channel_post_url or "",
                "vg_pg_ratio": p.vg_pg_ratio or "50/50",
                "nicotine_mg": p.nicotine_mg or "20mg",
                "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S.%f") if p.created_at else "",
                "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M:%S.%f") if p.updated_at else ""
            }
            for p in products
        ]
        with open(seed_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not auto-sync seed_products.json: {e}")

@router.get("", response_model=List[ProductResponse])
async def list_products(
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(Product).order_by(Product.id.desc())
    if is_active is not None:
        query = query.where(Product.is_active == is_active)
    result = await db.execute(query)
    return result.scalars().all()

@router.post("", response_model=ProductResponse)
async def create_product(
    prod_data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    new_product = Product(**prod_data.model_dump())
    db.add(new_product)
    await db.commit()
    await db.refresh(new_product)

    await auto_sync_seed_products(db)

    await ws_manager.broadcast({
        "type": "product_updated",
        "action": "create",
        "product_id": new_product.id
    })
    return new_product

@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Product).where(Product.id == product_id))
    product = res.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="პროდუქტი ვერ მოიძებნა")
    return product

@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    prod_data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    res = await db.execute(select(Product).where(Product.id == product_id))
    product = res.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="პროდუქტი ვერ მოიძებნა")

    update_dict = prod_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(product, field, value)

    await db.commit()
    await db.refresh(product)

    await auto_sync_seed_products(db)

    await ws_manager.broadcast({
        "type": "product_updated",
        "action": "update",
        "product_id": product.id
    })
    return product

@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    res = await db.execute(select(Product).where(Product.id == product_id))
    product = res.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="პროდუქტი ვერ მოიძებნა")

    await db.delete(product)
    await db.commit()

    await auto_sync_seed_products(db)

    await ws_manager.broadcast({
        "type": "product_updated",
        "action": "delete",
        "product_id": product_id
    })
    return {"status": "success", "message": "პროდუქტი წაიშალა"}

@router.post("/{product_id}/toggle-stock")
async def toggle_stock(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    res = await db.execute(select(Product).where(Product.id == product_id))
    product = res.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="პროდუქტი ვერ მოიძებნა")

    product.is_active = not product.is_active
    await db.commit()
    await db.refresh(product)

    await auto_sync_seed_products(db)

    return {"status": "success", "is_active": product.is_active}

@router.post("/bulk-delete")
async def bulk_delete_products(
    payload: BulkDeleteProductsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    if not payload.product_ids:
        return {"status": "success", "deleted_count": 0}

    res = await db.execute(
        delete(Product).where(Product.id.in_(payload.product_ids))
    )
    await db.commit()
    deleted_count = res.rowcount

    await auto_sync_seed_products(db)

    await ws_manager.broadcast({
        "type": "products_bulk_deleted",
        "product_ids": payload.product_ids,
        "count": deleted_count
    })
    return {"status": "success", "deleted_count": deleted_count}
