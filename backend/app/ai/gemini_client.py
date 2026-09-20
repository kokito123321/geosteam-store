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
        self.model_name = settings.GEMINI_MODEL or "gemini-3.8-flash"
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> Optional[genai.Client]:
        if not self._client:
            try:
                if settings.USE_VERTEX_AI or settings.GCP_PROJECT_ID:
                    if settings.GOOGLE_APPLICATION_CREDENTIALS:
                        cred_path = Path(settings.GOOGLE_APPLICATION_CREDENTIALS)
                        if cred_path.exists():
                            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_path.resolve())

                    project = settings.GCP_PROJECT_ID or None
                    location = settings.GCP_LOCATION or "global"
                    logger.info(f"Connecting to Google Cloud Vertex AI (Project: {project}, Location: {location})...")
                    self._client = genai.Client(
                        vertexai=True,
                        project=project,
                        location=location
                    )
                elif self.api_key:
                    logger.info("Connecting to Gemini API via API Key...")
                    self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Error initializing Gemini Client: {e}")
                self._client = None
        return self._client

    def update_api_key(self, new_key: str):
        self.api_key = new_key
        try:
            self._client = genai.Client(api_key=new_key)
        except Exception as e:
            logger.error(f"Failed to reload Gemini client with new key: {e}")

    def update_model_name(self, new_model: str):
        if new_model and new_model.strip():
            self.model_name = new_model.strip()
            logger.info(f"Gemini service switched to model: {self.model_name}")

    async def generate_channel_post(self, notes: str) -> str:
        from backend.app.ai.prompts import CHANNEL_POST_GENERATOR_SYSTEM_PROMPT
        return await self.get_response(
            user_message=f"გთხოვთ შექმნათ კარგი ტელეგრამ პოსტი შემდეგი მონაცემების მიხედვით:\n{notes}",
            system_instruction=CHANNEL_POST_GENERATOR_SYSTEM_PROMPT,
            temperature=0.7
        )

    async def get_response(
        self,
        user_message: str,
        system_instruction: str,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.5,
        customer_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generates a contextual response using Gemini 3.8 Flash, with tool calling support.
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
                max_output_tokens=1000,
                tools=[register_customer_order],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                )
            )

            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )

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
        """Intelligent fallback for customer chat when AI is initializing or temporarily offline."""
        msg = (user_message or "").lower().strip()
        if any(w in msg for w in ("გამარჯობა", "სალამი", "მოგესალმებით", "hello", "hi", "hey")):
            return (
                "გამარჯობა! 👋 კეთილი იყოს თქვენი მობრძანება **GeoSteam**-ში! 🇬🇪💨\n\n"
                "ჩვენთან დაგხვდებათ პრემიუმ ხარისხის ვეიპ სითხეები და მოწყობილობები.\n"
                "პროდუქციის სანახავად დააჭირეთ ქვემოთ ღილაკს **📦 კატალოგი** ან მომწერეთ რა გაინტერესებთ!"
            )
        if any(w in msg for w in ("სითხ", "ყიდვა", "შეძენა", "ფას", "კატალოგ", "არომატ", "liquid", "juice", "elfliq", "chaser")):
            return (
                "💨 **ჩვენი პროდუქციის სანახავად და შესაკვეთად:**\n\n"
                "გთხოვთ გამოიყენოთ ქვედა მენიუდან ღილაკი **📦 კატალოგი**.\n"
                "იქ იხილავთ ყველა ხელმისაწვდომ არომატს, ნიკოტინის დონეს და ფასებს, საიდანაც პირდაპირ შეგიძლიათ შეკვეთის გაფორმება! 🛒"
            )
        if any(w in msg for w in ("მიწოდება", "მისამართ", "ლოკაცია", "სად ხართ", "თბილისი", "რეგიონ", "yandex", "ტარიფ")):
            return (
                "🚚 **მიწოდების პირობები:**\n\n"
                "• **თბილისში:** მიწოდება ხორციელდება Yandex საკურიეროთი (მოგვწერეთ ზუსტი მისამართი და დაჯამდება თანხა).\n"
                "• **რეგიონებში:** ცენტრალურ მუნიციპალიტეტებში 9₾, სოფლებში 12₾.\n"
                "• **თვითგატანა:** შესაძლებელია ჩვენი ლოკაციიდან.\n\n"
                "დეტალებისთვის დააჭირეთ ღილაკს **ℹ️ მაღაზია / ლოკაცია**."
            )
        if any(w in msg for w in ("ოპერატორ", "მენეჯერ", "ადამიან", "დახმარებ", "operator")):
            return "👨‍💼 პირდაპირ მენეჯერთან დასაკავშირებლად დააჭირეთ ღილაკს: **🙋‍♂️ ოპერატორი**."
        return (
            "გამარჯობა! 🇬🇪💨 რით შემიძლია დაგეხმაროთ?\n\n"
            "გთხოვთ გამოიყენოთ ქვედა მენიუს ღილაკები:\n"
            "📦 **კატალოგი** - პროდუქციის ნახვა და შეკვეთა\n"
            "ℹ️ **მაღაზია / ლოკაცია** - მისამართი და მიწოდების პირობები\n"
            "🙋‍♂️ **ოპერატორი** - ცოცხალ მენეჯერთან დაკავშირება"
        )

    async def generate_channel_post(self, raw_notes: str, image_url: Optional[str] = None) -> str:
        """
        Generates a viral, high-converting Telegram post for the @Geosteamforeveryone channel.
        """
        if not self.client:
            return raw_notes

        system_prompt = (
            "შენ ხარ Geosteam / ჯეოსტიმის პროფესიონალი Telegram SMM მარკეტერი.\n"
            "შენი მიზანია შექმნა უმაღლესი დონის, მიმზიდველი და გაყიდვებზე ორიენტირებული პოსტი ტელეგრამ არხისთვის (@Geosteamforeveryone).\n\n"
            "პოსტის სტრუქტურის წესები:\n"
            "1. ეფექტური, თვალშისაცემი სათაური ემოჯებით (მაგ: 🔥 ახალი არომატი ჩამოვიდა! / 💨 შეხვდით ახალ ჩამოსვლას!)\n"
            "2. პროდუქტის მადისაღმძვრელი და დეტალური აღწერა\n"
            "3. მკაფიო სპეციფიკაციები Bullet point-ებით (💧 მოცულობა, 🧪 ნიკოტინი, 💨 VG/PG, 💰 ფასი)\n"
            "4. მკაფიო მოწოდება მოქმედებისკენ (CTA) — 'შესაკვეთად მოგვწერეთ პირადში ან გამოიყენეთ ბოტი!'\n"
            "5. გამოიყენე ჰეშთეგები: #Geosteam #VapeGeorgia #VapeTbilisi #PremiumJuice\n"
            "მნიშვნელოვანია: პოსტი უნდა იყოს მხოლოდ ქართულ ენაზე, გამართული, ცოცხალი და თანამედროვე სტილით."
        )

        try:
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.7,
                max_output_tokens=1000
            )

            prompt = f"გთხოვთ ამ მონაცემებზე დაყრდნობით შექმნა მზა Telegram პოსტი:\n\n{raw_notes}"
            if image_url:
                prompt += f"\n(თანდართულია ფოტო: {image_url})"

            resp = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config
            )

            if resp and resp.text:
                return resp.text.strip()
            return raw_notes
        except Exception as err:
            logger.error(f"Error generating channel post with Gemini: {err}", exc_info=True)
            return raw_notes

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
                "is_valid_receipt": True,
                "is_match": True,
                "extracted_amount": expected_amount,
                "extracted_iban": expected_iban,
                "reason": "AI Client not initialized (Fallback approval)"
            }

        prompt = f"""
შენ ხარ Geosteam-ის საბანკო ქვითრების AI ანალიტიკოსი და უსაფრთხოების აუდიტორი.
შეისწავლე ეს ფოტო/სქრინშოტი და დაადგინე:
1. არის თუ არა ეს ნამდვილი საბანკო გადარიცხვის ქვითარი / ჩეკი (მაგ: TBC, BOG / საქართველოს ბანკი, Liberty, Credo ან სხვა).
2. ამოიღე მიმღების IBAN ანგარიშის ნომერი (Recipient IBAN).
3. ამოიღე მიმღების სახელი (Recipient Name).
4. ამოიღე გადარიცხული თანხა (Amount GEL-ში, float რიცხვი).
5. ამოიღე გადამხდელის სახელი (Sender Name).
6. ამოიღე ტრანზაქციის თარიღი/დრო და დანიშნულება.

ჩვენი მაღაზიის (Geosteam) მოსალოდნელი მონაცემებია:
- მოსალოდნელი IBAN: "{expected_iban}"
- მოსალოდნელი თანხა: {expected_amount} GEL
- მიმღები: "{expected_recipient}"

შეადარე ქვითრიდან ამოღებული მონაცემები ჩვენს მოსალოდნელ მონაცემებს.
გაითვალისწინე:
- IBAN-ის შედარებისას უგულებელყავი გამოტოვებები და შეამოწმე ემთხვევა თუ არა ანგარიშის ნომერი.
- თანხის შედარებისას გადარიცხული თანხა უნდა იყოს მინიმუმ {expected_amount} GEL (დაშვებულია უმნიშვნელო დამრგვალება).

დააბრუნე მხოლოდ მკაცრი JSON ობიექტი შემდეგი ფორმატით (დამატებითი ტექსტის გარეშე):
{{
  "is_valid_receipt": true,
  "extracted_iban": "GE...",
  "extracted_recipient": "...",
  "extracted_amount": 0.0,
  "currency": "GEL",
  "sender_name": "...",
  "transaction_date": "...",
  "is_iban_match": true,
  "is_amount_match": true,
  "is_match": true,
  "fraud_score": 0,
  "reason": "მოკლე ქართული ახსნა რა ემთხვევა ან რა არ ემთხვევა"
}}
"""
        try:
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            config = types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json"
            )
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=[image_part, prompt],
                config=config
            )

            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

            result = json.loads(raw_text)

            extracted_iban = str(result.get("extracted_iban", "")).replace(" ", "").upper()
            clean_expected_iban = str(expected_iban).replace(" ", "").upper()
            extracted_amount = float(result.get("extracted_amount", 0.0) or 0.0)

            if clean_expected_iban and extracted_iban:
                iban_ok = (clean_expected_iban in extracted_iban) or (extracted_iban in clean_expected_iban)
            else:
                iban_ok = bool(result.get("is_iban_match", True))

            amount_ok = (extracted_amount >= (expected_amount - 0.5)) if expected_amount > 0 else True
            is_valid_receipt = bool(result.get("is_valid_receipt", True))

            final_match = bool(is_valid_receipt and iban_ok and amount_ok and result.get("is_match", True))
            result["is_match"] = final_match
            result["is_iban_match"] = iban_ok
            result["is_amount_match"] = amount_ok

            return result
        except Exception as e:
            logger.error(f"Gemini Vision Receipt verification error: {e}", exc_info=True)
            return {
                "is_valid_receipt": True,
                "is_match": True,
                "confidence": "low",
                "extracted_amount": expected_amount,
                "extracted_iban": expected_iban,
                "reason": f"AI ანალიზის შეცდომა: {str(e)}"
            }

gemini_service = GeminiService()

