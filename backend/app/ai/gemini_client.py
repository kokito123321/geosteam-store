import os
import json
import random
import logging
import contextvars
from typing import List, Dict, Any, Optional
from pathlib import Path
from sqlalchemy import select
from google import genai
from google.genai import types

from backend.app.config import settings
from backend.app.database import async_session_maker
from backend.app.models import Product, Order, Customer, StoreSettings
from backend.app.services.notifications import ws_manager

logger = logging.getLogger(__name__)

_current_customer_context: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar("_current_customer_context", default={})

async def register_customer_order(
    product_name_or_flavor: str,
    quantity: int = 1,
    delivery_method: str = "pickup",
    delivery_address: str = "",
    payment_method: str = "bank_transfer",
    customer_notes: str = ""
) -> Dict[str, Any]:
    """
    Creates an official customer order in the system, decrements stock,
    and returns bank transfer credentials or confirmation.
    """
    from backend.app.services.notifications import ws_manager, notify_new_order
    from backend.app.bot.bot_instance import bot_manager

    ctx = _current_customer_context.get() or {}
    customer_telegram_id = ctx.get("telegram_id", 0)
    customer_name = ctx.get("name", "მომხმარებელი")
    customer_phone = ctx.get("phone", "")

    async with async_session_maker() as session:
        # Find product by fuzzy/ilike matching name
        clean_name = product_name_or_flavor.strip()
        res_p = await session.execute(
            select(Product).where(
                Product.name.ilike(f"%{clean_name}%"),
                Product.is_active == True
            ).limit(1)
        )
        prod = res_p.scalars().first()
        if not prod:
            # Fallback to any active product
            res_all = await session.execute(select(Product).where(Product.is_active == True))
            prod = res_all.scalars().first()

        if not prod:
            return {"success": False, "error": "პროდუქტი კატალოგში ვერ მოიძებნა"}

        qty = max(1, int(quantity))
        if prod.stock_quantity < qty:
            return {
                "success": False,
                "error": f"სამწუხაროდ {prod.name} მარაგში დარჩენილია მხოლოდ {prod.stock_quantity} ცალი"
            }

        # Decrement stock immediately
        prod.stock_quantity -= qty
        res_s = await session.execute(select(StoreSettings).limit(1))
        st = res_s.scalars().first()

        center_fee = getattr(st, 'delivery_regions_center_fee', 9.0) if st else 9.0
        village_fee = getattr(st, 'delivery_regions_village_fee', 12.0) if st else 12.0

        dm_lower = str(delivery_method).lower()
        delivery_fee = 0.0

        if any(w in dm_lower for w in ["village", "სოფელ", "სოფ"]):
            delivery_fee = village_fee
            formatted_delivery = f"რეგიონი (სოფელი - {village_fee:.0f}₾)"
        elif any(w in dm_lower for w in ["region", "center", "რეგიონ", "ცენტრ", "მუნიციპალ", "ქალაქ"]):
            delivery_fee = center_fee
            formatted_delivery = f"რეგიონი (ცენტრი - {center_fee:.0f}₾)"
        elif any(w in dm_lower for w in ["pickup", "თვითგატან", "მაღაზია"]):
            delivery_fee = 0.0
            formatted_delivery = "თვითგატანა (მაღაზიიდან)"
        else:
            # Default is Tbilisi Yandex Courier
            delivery_fee = 0.0
            formatted_delivery = "თბილისი (Yandex საკურიერო)"

        total_amount = float(prod.price * qty) + delivery_fee
        order_number = f"ORD-{random.randint(10000, 99999)}"

        new_order = Order(
            order_number=order_number,
            customer_telegram_id=customer_telegram_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            items_json=json.dumps([{
                "product_id": prod.id,
                "name": prod.name,
                "price": prod.price,
                "quantity": qty,
                "nicotine_mg": prod.nicotine_mg
            }]),
            total_amount=total_amount,
            delivery_method=formatted_delivery,
            delivery_address=delivery_address or ("მაღაზიიდან თვითგატანა" if "თვითგატანა" in formatted_delivery else ""),
            payment_method=payment_method,
            payment_status="pending",
            order_status="new",
            notes=customer_notes.strip() if customer_notes else ""
        )
        session.add(new_order)

        # Update customer state
        if customer_telegram_id:
            res_c = await session.execute(select(Customer).where(Customer.telegram_id == customer_telegram_id))
            cust = res_c.scalars().first()
            if cust:
                if payment_method == "bank_transfer":
                    cust.order_state = f"AWAITING_RECEIPT_{new_order.id}"
                else:
                    cust.order_state = "IDLE"

        await session.commit()
        await session.refresh(new_order)
        await session.refresh(prod)

        # Dispatch 3-channel notifications (Telegram Admin Alert, WebSocket Live Audio, Email)
        try:
            await notify_new_order(new_order, st, bot_manager.bot_app)
        except Exception as e:
            logger.error(f"Error in notify_new_order: {e}")

        # Broadcast real-time websocket events to Dashboard
        await ws_manager.broadcast({
            "type": "new_order",
            "order": {
                "id": new_order.id,
                "order_number": new_order.order_number,
                "customer_name": new_order.customer_name,
                "customer_phone": new_order.customer_phone,
                "total_amount": new_order.total_amount,
                "delivery_method": new_order.delivery_method,
                "payment_method": new_order.payment_method,
                "payment_status": new_order.payment_status,
                "order_status": new_order.order_status,
                "items": json.loads(new_order.items_json),
                "created_at": new_order.created_at.isoformat() if new_order.created_at else ""
            }
        })

        await ws_manager.broadcast({
            "type": "product_updated",
            "product_id": prod.id,
            "name": prod.name,
            "price": prod.price,
            "stock": prod.stock_quantity
        })

        return {
            "success": True,
            "order_id": new_order.id,
            "order_number": new_order.order_number,
            "product_name": prod.name,
            "quantity": qty,
            "total_amount": total_amount,
            "bank_name": st.bank_name if st else "საქართველოს ბანკი",
            "bank_iban": st.bank_iban if st else "",
            "bank_recipient": (st.bank_recipient if st and st.bank_recipient else "Geosteam")
        }


class GeminiService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model_name = settings.GEMINI_MODEL or "gemini-3.6-flash"
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> Optional[genai.Client]:
        if not self._client:
            try:
                # 1. First prioritize GEMINI_API_KEY / GOOGLE_API_KEY if available (standard Developer API for cloud & local)
                api_key = (self.api_key or settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")).strip().strip('"').strip("'")
                if api_key:
                    logger.info(f"Connecting to Gemini API via API Key ({api_key[:6]}...)...")
                    self._client = genai.Client(api_key=api_key)
                elif settings.USE_VERTEX_AI or settings.GCP_PROJECT_ID or os.environ.get("GCP_PROJECT_ID"):
                    if settings.GOOGLE_APPLICATION_CREDENTIALS:
                        cred_path = Path(settings.GOOGLE_APPLICATION_CREDENTIALS)
                        if cred_path.exists():
                            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_path.resolve())

                    project = settings.GCP_PROJECT_ID or os.environ.get("GCP_PROJECT_ID") or None
                    location = settings.GCP_LOCATION or "global"
                    logger.info(f"Connecting to Google Cloud Vertex AI (Project: {project}, Location: {location})...")
                    self._client = genai.Client(
                        vertexai=True,
                        project=project,
                        location=location
                    )
            except Exception as e:
                logger.error(f"Error initializing Gemini Client: {e}")
                self._client = None
        return self._client

    def update_api_key(self, new_key: str):
        self.api_key = new_key.strip().strip('"').strip("'")
        try:
            self._client = genai.Client(api_key=self.api_key)
        except Exception as e:
            logger.error(f"Failed to reload Gemini client with new key: {e}")

    def update_model_name(self, new_model: str):
        if new_model and new_model.strip():
            self.model_name = new_model.strip()
            logger.info(f"Gemini service switched to model: {self.model_name}")

    async def get_response(
        self,
        user_message: str,
        system_instruction: str,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.5,
        customer_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generates a contextual response using Gemini, with tool calling support and model cascade.
        """
        if not self.client:
            return self._smart_rule_based_fallback(user_message)

        if customer_context:
            _current_customer_context.set(customer_context)

        try:
            contents = []
            if history:
                for msg in history[-10:]:
                    role = "user" if msg.get("sender") == "user" else "model"
                    contents.append(
                        types.Content(
                            role=role,
                            parts=[types.Part.from_text(text=msg.get("text", ""))]
                        )
                    )
            
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=user_message)]
                )
            )

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
                max_output_tokens=8192,
                tools=[register_customer_order],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                )
            )

            # Model cascade
            candidate_models = [self.model_name]
            for fallback_m in ["gemini-3.6-flash", "gemini-3.8-flash"]:
                if fallback_m not in candidate_models:
                    candidate_models.append(fallback_m)

            response = None
            last_err = None
            for model_cand in candidate_models:
                try:
                    response = await self.client.aio.models.generate_content(
                        model=model_cand,
                        contents=contents,
                        config=config
                    )
                    if response:
                        self.model_name = model_cand
                        break
                except Exception as ex:
                    last_err = ex
                    logger.warning(f"Model {model_cand} call failed: {ex}. Trying next model...")

            if not response:
                raise last_err or Exception("All Gemini models failed")

            current_turn_contents = list(contents)

            while response.function_calls:
                current_turn_contents.append(response.candidates[0].content)

                function_responses = []
                for fc in response.function_calls:
                    fname = fc.name
                    fargs = fc.args or {}
                    logger.info(f"Customer Gemini Bot executing tool: {fname} with args: {fargs}")

                    tool_result = None
                    try:
                        if fname == "register_customer_order":
                            tool_result = await register_customer_order(**fargs)
                        else:
                            tool_result = {"error": f"Unknown tool: {fname}"}
                    except Exception as err:
                        logger.error(f"Error executing customer tool {fname}: {err}", exc_info=True)
                        tool_result = {"error": str(err)}

                    function_responses.append(
                        types.Part.from_function_response(
                            name=fname,
                            response={"result": tool_result}
                        )
                    )

                current_turn_contents.append(
                    types.Content(
                        role="user",
                        parts=function_responses
                    )
                )

                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=current_turn_contents,
                    config=config
                )

            if response and response.text:
                return response.text.strip()
            return self._smart_rule_based_fallback(user_message)

        except Exception as e:
            logger.error(f"Gemini API generation error: {e}", exc_info=True)
            return self._smart_rule_based_fallback(user_message)

    def _smart_rule_based_fallback(self, user_message: str) -> str:
        """Friendly, natural fallback for customer chat with accurate store info."""
        msg = (user_message or "").lower().strip()
        if any(w in msg for w in ("გამარჯობა", "სალამი", "მოგესალმებით", "hello", "hi", "hey", "ზდაროვა", "გაუმარჯოს")):
            return (
                "გაუმარჯოს! 💨 GeoSteam-ში ვართ.\n\n"
                "რა გაინტერესებს — სითხეები, არომატები, ლოკაცია თუ მიწოდება? მითხარი და დაგეხმარები!"
            )
        if any(w in msg for w in ("ლოკაცია", "მისამართ", "google", "map", "ლინკ", "ბმულ", "სად ხართ", "მოსვლა", "სად მოვიდე", "მისვლა", "ადგილზე")):
            return (
                "📍 **ჩვენი ლოკაცია / Google Maps ბმული:**\n"
                "https://maps.app.goo.gl/5Ehyo2jkQv91ChnG8\n\n"
                "თვითგატანა მაღაზიიდან სრულიად უფასოა! 💨"
            )
        if any(w in msg for w in ("ანგარიშ", "იბან", "iban", "რეკვიზიტ", "გადარიცხვ", "ჩარიცხვ")):
            return (
                "💳 **საბანკო რეკვიზიტები გადასარიცხად:**\n"
                "• ბანკი: BOG (საქართველოს ბანკი)\n"
                "• IBAN: `GE58BG0000000100906441`\n"
                "• მიმღები: ლ.ჩ\n\n"
                "გადარიცხვის შემდეგ გამოგვიგზავნეთ ქვითრის სქრინშოტი აქ! 🧾"
            )
        if any(w in msg for w in ("სითხ", "ყიდვა", "შეძენა", "ფას", "კატალოგ", "არომატ", "liquid", "juice", "elfliq", "chaser")):
            return (
                "💨 გვაქვს პრემიუმ ვეიპ სითხეების ფართო არჩევანი (50/50 და 70/30)!\n"
                "მოგვწერე რა არომატი (ცივი, ხილის, ტკბილი) ან ნიკოტინის დონე გინდა და მაშინვე შეგირჩევთ."
            )
        if any(w in msg for w in ("მიწოდება", "კურიერ", "yandex", "ტარიფ", "რეგიონ")):
            return (
                "🚚 **მიწოდების პირობები:**\n"
                "• **თბილისში:** Yandex კურიერით (მოგვწერე მისამართი და გამოგიგზავნით).\n"
                "• **რეგიონებში:** ცენტრებში 9₾, სოფლებში 12₾ (3 სამუშაო დღეში).\n"
                "• **თვითგატანა:** უფასოა ჩვენი ლოკაციიდან: https://maps.app.goo.gl/5Ehyo2jkQv91ChnG8"
            )
        if any(w in msg for w in ("ოპერატორ", "მენეჯერ", "ადამიან", "დახმარებ", "operator")):
            return "👨‍💼 ოპერატორი მალე შემოგიერთდებათ პირადში დასახმარებლად!"
        return (
            "გისმენ! 💨 რით დაგეხმარო? შეგიძლია მკითხო სითხეებზე, არომატებზე, ლოკაციაზე ან მიწოდებაზე."
        )

    def _generate_smart_fallback_post(self, raw_notes: str, image_url: Optional[str] = None) -> str:
        """
        Intelligent rule-based copywriter engine that transforms any raw notes into a
        viral, beautifully-formatted Georgian Telegram post for @Geosteamforeveryone.
        """
        import re
        lines = [line.strip() for line in (raw_notes or "").split("\n") if line.strip()]
        if not lines:
            return raw_notes

        flavor_emojis = {
            "ალუბალ": "🍒❄️",
            "cherry": "🍒❄️",
            "ბანან": "🍌",
            "banana": "🍌",
            "მოცვ": "🫐",
            "blueberry": "🫐",
            "ჟოლო": "🫐🍬",
            "raspberry": "🫐🍬",
            "კარამელ": "🍮🍬",
            "caramel": "🍮🍬",
            "მარწყვ": "🍓",
            "strawberry": "🍓",
            "მანგო": "🥭",
            "mango": "🥭",
            "საზამთრო": "🍉",
            "watermelon": "🍉",
            "ვაშლ": "🍏",
            "apple": "🍏",
            "ატამ": "🍑",
            "peach": "🍑",
            "ლიმონ": "🍋",
            "lemon": "🍋",
            "ყინულ": "❄️",
            "ice": "❄️",
            "პიტნ": "🌿❄️",
            "mint": "🌿❄️",
            "ყავა": "☕",
            "coffee": "☕",
            "ვანილ": "🍦",
            "vanilla": "🍦",
            "ყურძენ": "🍇",
            "grape": "🍇",
            "ანანას": "🍍",
            "pineapple": "🍍",
            "ენერგეტიკ": "⚡🔋",
            "energy": "⚡🔋",
            "თამბაქო": "🍂",
            "tobacco": "🍂"
        }

        flavor_items = []
        price_str = "20 ₾"
        action_found = False

        for line in lines:
            line_lower = line.lower()
            price_match = re.search(r'(\d+)\s*(?:ლარ|₾|gel|lari)?', line_lower)
            if any(p_word in line_lower for p_word in ["ფასი", "ლარ", "₾", "აქცია", "sale", "price"]) and price_match:
                price_str = f"{price_match.group(1)} ₾"
                if "აქცი" in line_lower:
                    action_found = True
                continue

            if any(intro_word in line_lower for intro_word in ["დაგვემატა", "ჩამოვიდა", "ახალი", "სითხეები", "მოგესალმებით", "გამარჯობა"]):
                continue

            matched_emoji = "✨"
            for k, emoji in flavor_emojis.items():
                if k in line_lower:
                    matched_emoji = emoji
                    break

            flavor_items.append(f"• {matched_emoji} **{line}**")

        headline = "🔥💣 **გემოების ნამდვილი აფეთქება ჯეოსტიმში! ახალი სითხეები უკვე ადგილზეა!** 💨🇬🇪"
        if action_found:
            headline = "🔥💣 **გიჟური აქცია ჯეოსტიმში! ახალი პრემიუმ სითხეები სპეციალურ ფასად!** 💥💨"

        items_formatted = "\n".join(flavor_items) if flavor_items else "\n".join([f"• ✨ **{l}**" for l in lines])

        post = (
            f"{headline}\n\n"
            f"ორთქლის მოყვარულებო, თქვენი Pod-ები მოამზადეთ! ჩვენთან ჩამოვიდა უმაღლესი ხარისხის, "
            f"გაჯერებული და დაუვიწყარი არომატები, რომლებიც პირველივე ნაფაზიდან მოგხიბლავთ:\n\n"
            f"✨ **ახალი არომატების ასორტიმენტი:**\n"
            f"{items_formatted}\n\n"
            f"---\n"
            f"📌 **პროდუქტის მახასიათებლები:**\n"
            f"• 💧 **მოცულობა:** 30 მლ\n"
            f"• ⚡ **ნიკოტინის ტიპი:** Salt Nicotine (20mg / 50mg)\n"
            f"• ⚖️ **VG/PG ბალანსი:** 50/50 (იდეალურია Pod სისტემებისთვის)\n"
            f"• 💰 **სპეციალური ფასი:** **{price_str}** 💥\n\n"
            f"---\n"
            f"🚀 **მარაგი შეზღუდულია, იჩქარეთ!**\n\n"
            f"🛒 **შესაკვეთად მოგვწერეთ პირადში ან გამოიყენეთ ჩვენი ბოტი:** @GeoSteamSupportBot\n"
            f"🛵 **სწრაფი მიტანა თბილისში Yandex კურიერით | რეგიონებში 3 დღეში | თვითგატანა მაღაზიიდან**\n\n"
            f"#Geosteam #ქართულიორთქლი #VapeGeorgia #VapeTbilisi #ELiquid #PremiumVape #VapeShopGeo"
        )
        return post

    async def generate_channel_post(self, raw_notes: str, image_url: Optional[str] = None) -> str:
        """
        Generates a creative, viral, high-converting Telegram post for @Geosteamforeveryone.
        Falls back to intelligent copywriter engine if Gemini API is unavailable.
        """
        if not (raw_notes or "").strip():
            return ""

        system_prompt = (
            "შენ ხარ Geosteam-ის (ჯეოსტიმი / ქართული ორთქლი 🇬🇪💨) წამყვანი SMM და Copywriting ექსპერტი.\n"
            "შენი მისიაა ადმინისტრატორის მიერ მოწოდებული მოკლე, მშრალი ჩანაწერებიდან შექმნა მაქსიმალურად კრეატიული, "
            "თვალშისაცემი, მადისაღმძვრელი და გაყიდვებზე ორიენტირებული Telegram პოსტი არხისთვის (@Geosteamforeveryone).\n\n"
            "🔥 პოსტის აუცილებელი სტრუქტურა:\n"
            "1. **თვალშისაცემი ჰედლაინი (Catchy Hook):** გამოიყენე ცეცხლოვანი და თემატური ემოჯები (მაგ: 🔥💨 ექსკლუზივი ჯეოსტიმში! / 💣 ტროპიკული აფეთქება ჩამოვიდა!).\n"
            "2. **მადისაღმძვრელი Storytelling / გემოს აღწერა:** დეტალურად და ცოცხლად აღწერე არომატის ნოტები (ტკბილი, ცივი, მჟავე, ხილის წვნიანი ტონები), რათა მკითხველს პირველივე წაკითხვისას მოუნდეს გასინჯვა.\n"
            "3. **მკაფიო მახასიათებლები (Bullets & Emojis):**\n"
            "   • 💧 **მოცულობა:** [30ml / 60ml და ა.შ.]\n"
            "   • ⚡ **ნიკოტინი:** [20mg Salt / 50mg / 3mg და ა.შ.]\n"
            "   • ⚖️ **VG/PG ბალანსი:** [50/50 Pod მოწყობილობებისთვის ან 70/30]\n"
            "   • 💰 **ფასი:** [მითითებული ფასი] ₾\n"
            "4. **მოწოდება მოქმედებისკენ (Call To Action):**\n"
            "   • 🛒 **შესაკვეთად მოგვწერეთ პირადში ან გამოიყენეთ ჩვენი ბოტი:** @GeoSteamSupportBot\n"
            "   • 🛵 **სწრაფი მიტანა თბილისში Yandex კურიერით | რეგიონებში 3 დღეში | თვითგატანა მაღაზიიდან**\n"
            "5. **ჰეშთეგები:** #Geosteam #ქართულიორთქლი #VapeGeorgia #VapeTbilisi #ELiquid #PremiumVape\n\n"
            "⚠️ წესები:\n"
            "- პოსტი დაწერე მხოლოდ ქართულად, უმაღლესი ხარისხის მარკეტინგული ქართულით.\n"
            "- არასდროს გამოიყენო 'შპს' ან ოფიციალური ბიუროკრატიული ტონი.\n"
            "- ტექსტი იყოს ცოცხალი, ენერგიული და სრულად დასრულებული."
        )

        if self.client:
            candidate_models = [
                self.model_name,
                "gemini-2.5-flash",
                "gemini-2.0-flash",
                "gemini-1.5-flash",
                "gemini-1.5-pro",
                "gemini-2.0-flash-lite"
            ]
            unique_models = []
            for m in candidate_models:
                if m and m not in unique_models:
                    unique_models.append(m)

            for model_cand in unique_models:
                try:
                    config = types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.85,
                        max_output_tokens=4096
                    )

                    prompt = f"გთხოვთ ამ მოკლე ჩანაწერებზე დაყრდნობით შექმნა სრული, კრეატიული და გაყიდვადი Telegram პოსტი:\n\n{raw_notes}"
                    if image_url:
                        prompt += f"\n(თანდართულია პროდუქტის ფოტო: {image_url})"

                    resp = await self.client.aio.models.generate_content(
                        model=model_cand,
                        contents=prompt,
                        config=config
                    )

                    if resp and resp.text and len(resp.text.strip()) > 40:
                        self.model_name = model_cand
                        return resp.text.strip()
                except Exception as err:
                    logger.warning(f"Error generating channel post with model {model_cand}: {err}")

        # Intelligent fallback if API is unavailable
        return self._generate_smart_fallback_post(raw_notes, image_url)

    async def verify_receipt_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        expected_iban: str = "",
        expected_amount: float = 0.0,
        expected_recipient: str = "Geosteam"
    ) -> Dict[str, Any]:
        """
        Uses Gemini Multimodal Vision to inspect bank transfer receipts,
        extract recipient IBAN and transferred amount, and verify against Geosteam's credentials.
        """
        if not self.client:
            return {
                "is_valid_receipt": False,
                "is_match": False,
                "extracted_amount": 0.0,
                "extracted_iban": "",
                "reason": "AI კლიენტი არ არის ინიციალიზებული (საჭიროებს ოპერატორის გადამოწმებას)"
            }

        prompt = f"""
შენ ხარ Geosteam-ის საბანკო ქვითრების მკაცრი AI ანალიტიკოსი და უსაფრთხოების აუდიტორი.
შეისწავლე ეს ფოტო/სქრინშოტი და ზედმიწევნით შეამოწმე:
1. არის თუ არა ეს ნამდვილი საბანკო გადარიცხვის ქვითარი / ჩეკი (მაგ: საქართველოს ბანკი / BOG, TBC, Liberty, Credo ან სხვა ბანკი).
2. ამოიღე მიმღების IBAN ანგარიშის ნომერი (Recipient IBAN).
3. ამოიღე გადარიცხული თანხა (Amount GEL-ში, float რიცხვი).
4. ამოიღე მიმღების სახელი (Recipient Name).
5. ამოიღე გადამხდელის სახელი (Sender Name).

ჩვენი მაღაზიის (Geosteam) მოსალოდნელი მონაცემებია:
- მოსალოდნელი IBAN: "{expected_iban}"
- მოსალოდნელი ზუსტი თანხა: {expected_amount:.2f} GEL
- მიმღები: "{expected_recipient}"

მკაცრი წესები შედარებისთვის:
- თუ ფოტოზე საერთოდ არ არის საბანკო ქვითარი ან არის სხვა რამის სქრინშოტი -> is_valid_receipt = false, is_match = false
- თუ გადარიცხვა შესრულებულია მობილურის ნომერზე (P2P), პირად ანგარიშზე ან სხვა IBAN-ზე (და არა "{expected_iban}") -> is_iban_match = false, is_match = false
- თუ გადარიცხული თანხა არ შეესაბამება {expected_amount:.2f} GEL-ს (მაგ: 33₾-ის მაგივრად 65₾ ან 10₾-ია) -> is_amount_match = false, is_match = false
- is_match უნდა იყოს true მხოლოდ და მხოლოდ იმ შემთხვევაში, თუ IBAN-იც და თანხაც ზუსტად ემთხვევა Geosteam-ის მონაცემებს!

დააბრუნე მხოლოდ მკაცრი JSON შემდეგი ფორმატით:
{{
  "is_valid_receipt": false,
  "extracted_iban": "GE...",
  "extracted_recipient": "...",
  "extracted_amount": 0.0,
  "currency": "GEL",
  "sender_name": "...",
  "transaction_date": "...",
  "is_iban_match": false,
  "is_amount_match": false,
  "is_match": false,
  "fraud_score": 0,
  "reason": "მოკლე ქართული ახსნა რა ემთხვევა და რა არ ემთხვევა"
}}
"""
        try:
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            config = types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json"
            )

            candidate_models = [self.model_name]
            for fallback_m in ["gemini-3.6-flash", "gemini-3.8-flash"]:
                if fallback_m not in candidate_models:
                    candidate_models.append(fallback_m)

            response = None
            last_err = None
            for model_cand in candidate_models:
                try:
                    response = await self.client.aio.models.generate_content(
                        model=model_cand,
                        contents=[image_part, prompt],
                        config=config
                    )
                    if response:
                        self.model_name = model_cand
                        break
                except Exception as ex:
                    last_err = ex
                    logger.warning(f"Vision call with {model_cand} failed: {ex}")

            if not response:
                raise last_err or Exception("All Gemini vision models failed")

            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

            result = json.loads(raw_text)

            extracted_iban = str(result.get("extracted_iban") or "").replace(" ", "").upper()
            clean_expected_iban = str(expected_iban).replace(" ", "").upper()
            extracted_amount = float(result.get("extracted_amount") or 0.0)

            # Strict IBAN Check
            if clean_expected_iban:
                iban_ok = bool(extracted_iban and (clean_expected_iban in extracted_iban or extracted_iban in clean_expected_iban))
            else:
                iban_ok = bool(result.get("is_iban_match", False))

            # Strict Amount Check (must match within 0.2 GEL tolerance)
            if expected_amount > 0:
                amount_ok = abs(extracted_amount - expected_amount) <= 0.2
            else:
                amount_ok = bool(result.get("is_amount_match", False))

            is_valid_receipt = bool(result.get("is_valid_receipt", False))

            final_match = bool(is_valid_receipt and iban_ok and amount_ok and (result.get("is_match") is True))
            result["is_match"] = final_match
            result["is_iban_match"] = iban_ok
            result["is_amount_match"] = amount_ok

            if not final_match and not result.get("reason"):
                reasons = []
                if not is_valid_receipt:
                    reasons.append("არ არის ვალიდური საბანკო გადარიცხვის ქვითარი")
                if not iban_ok:
                    reasons.append(f"მიმღები ანგარიში ({extracted_iban or 'უცნობი'}) არ ემთხვევა მაღაზიის IBAN-ს ({clean_expected_iban})")
                if not amount_ok:
                    reasons.append(f"გადარიცხული თანხა ({extracted_amount:.2f} GEL) არ ემთხვევა შეკვეთის თანხას ({expected_amount:.2f} GEL)")
                result["reason"] = "; ".join(reasons)

            return result
        except Exception as e:
            logger.error(f"Gemini Vision Receipt verification error: {e}", exc_info=True)
            return {
                "is_valid_receipt": False,
                "is_match": False,
                "confidence": "none",
                "extracted_amount": 0.0,
                "extracted_iban": "",
                "reason": f"AI-მ ვერ შეძლო ქვითრის ავტომატური ამოკითხვა: {str(e)}"
            }

gemini_service = GeminiService()

