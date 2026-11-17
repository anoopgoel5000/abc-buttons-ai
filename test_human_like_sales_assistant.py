"""
Test Suite for ABC Buttons: Human-Like 24x7 WhatsApp AI Sales Assistant
Covers all 15 Mandatory Commercial Qualification & Reliability Scenarios:
1. Hi -> Agoya buttons -> Photo -> 200 Gross -> Company -> City
2. Photo-only inquiry
3. Buyer asks for price immediately
4. Buyer asks for ready stock
5. Buyer changes quantity
6. Returning customer with existing details
7. Customer provides all details in one message (all-in-one)
8. Midnight inquiry (after-hours)
9. Customer requests similar samples
10. Customer asks for custom manufacturing
11. Human salesperson takes over
12. Photo download failure
13. CRM save failure & graceful recovery
14. Duplicate WhatsApp webhook delivery (Idempotency)
15. Buyer stops replying midway and returns later
"""

import unittest
import asyncio
import os
import json
import datetime
from unittest.mock import patch

# Set testing environment variable
os.environ["STREAMLIT_TESTING"] = "1"

import db
import webhook_bot

DUMMY_JPG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\xff\xd9"

class TestHumanLikeSalesAssistant(unittest.TestCase):
    def setUpClass():
        db.init_db()

    def setUp(self):
        # Clean any test rows
        with db.get_db_connection() as conn:
            conn.execute("DELETE FROM inbound_message_lifecycle WHERE msg_id LIKE 'TEST_HL_%'")
            conn.execute("DELETE FROM processed_messages WHERE msg_id LIKE 'TEST_HL_%'")
            conn.execute("DELETE FROM live_inquiries WHERE id LIKE 'INQ-%' OR phone LIKE '%7777777%'")
            conn.execute("DELETE FROM outbound_delivery_logs WHERE phone LIKE '%7777777%'")
            conn.execute("DELETE FROM buyer_sessions WHERE phone LIKE '%7777777%'")

    def tearDown(self):
        with db.get_db_connection() as conn:
            conn.execute("DELETE FROM inbound_message_lifecycle WHERE msg_id LIKE 'TEST_HL_%'")
            conn.execute("DELETE FROM processed_messages WHERE msg_id LIKE 'TEST_HL_%'")
            conn.execute("DELETE FROM live_inquiries WHERE id LIKE 'INQ-%' OR phone LIKE '%7777777%'")
            conn.execute("DELETE FROM outbound_delivery_logs WHERE phone LIKE '%7777777%'")
            conn.execute("DELETE FROM buyer_sessions WHERE phone LIKE '%7777777%'")

    def test_01_full_conversational_intake_flow(self):
        """Test 1: Hi -> Agoya buttons -> Photo -> 200 Gross -> Company -> City."""
        phone = "917777777701"
        sent_texts = []
        sent_images = []

        def mock_text(to, txt, *args, **kwargs):
            sent_texts.append(txt)
            return {"status": "success"}

        def mock_image(to, img, cap, *args, **kwargs):
            sent_images.append(cap)
            return {"status": "success"}

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=mock_text), \
             patch.object(webhook_bot, 'send_whatsapp_image', side_effect=mock_image), \
             patch.object(webhook_bot, 'download_whatsapp_media', return_value=DUMMY_JPG):

            # Turn 1: Buyer says "Hi"
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Pawan"}}],
                "messages": [{"id": "TEST_HL_01_1", "from": phone, "type": "text", "text": {"body": "Hi"}}]
            }))
            self.assertEqual(len(sent_texts), 1)
            self.assertIn("swagat", sent_texts[-1].lower())

            # Turn 2: Buyer says "Agoya buttons"
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Pawan"}}],
                "messages": [{"id": "TEST_HL_01_2", "from": phone, "type": "text", "text": {"body": "Agoya buttons chahiye"}}]
            }))
            self.assertEqual(len(sent_images), 0, "AI must NEVER send catalog images automatically!")
            self.assertIn("agoya", sent_texts[-1].lower())
            self.assertIn("photo", sent_texts[-1].lower())

            # Turn 3: Buyer sends photo
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Pawan"}}],
                "messages": [{"id": "TEST_HL_01_3", "from": phone, "type": "image", "image": {"id": "med_01", "caption": ""}}]
            }))
            self.assertEqual(len(sent_images), 0, "No catalog photos sent on photo arrival!")
            self.assertIn("inquiry id:", sent_texts[-1].lower())
            self.assertIn("quantity", sent_texts[-1].lower())

            # Turn 4: Buyer says "200 Gross"
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Pawan"}}],
                "messages": [{"id": "TEST_HL_01_4", "from": phone, "type": "text", "text": {"body": "200 Gross"}}]
            }))
            self.assertIn("company", sent_texts[-1].lower())

            # Turn 5: Buyer says "Apex Fashions, Surat"
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Pawan"}}],
                "messages": [{"id": "TEST_HL_01_5", "from": phone, "type": "text", "text": {"body": "Apex Fashions, Surat"}}]
            }))
            self.assertIn("apex fashions", sent_texts[-1].lower())

            # Verify in DB
            inqs = db.load_live_inquiries_db()
            matched = [i for i in inqs if i["phone"] == db.normalize_phone(phone)]
            self.assertEqual(len(matched), 1)
            self.assertEqual(matched[0]["quantity"], 200)
            self.assertEqual(matched[0]["company"], "Apex Fashions")
            self.assertEqual(matched[0]["city"], "Surat")
            self.assertEqual(matched[0]["inquiry_status"], "READY_FOR_SALES")

    def test_02_photo_only_inquiry(self):
        """Test 2: Photo-only inquiry receives immediate acknowledgment & asks single primary question."""
        phone = "917777777702"
        sent_texts = []
        sent_images = []

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)), \
             patch.object(webhook_bot, 'send_whatsapp_image', side_effect=lambda *a, **kw: sent_images.append(a)), \
             patch.object(webhook_bot, 'download_whatsapp_media', return_value=DUMMY_JPG):

            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_02", "from": phone, "type": "image", "image": {"id": "med_02", "caption": ""}}]
            }))
            self.assertEqual(len(sent_images), 0)
            self.assertTrue(len(sent_texts) >= 1)
            self.assertIn("inquiry id:", sent_texts[0].lower())
            self.assertIn("quantity", sent_texts[0].lower())

    def test_03_buyer_asks_for_price_immediately(self):
        """Test 3: Buyer asks for price -> defer politely to Sales Team, never invent rates."""
        phone = "917777777703"
        sent_texts = []

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)):
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_03", "from": phone, "type": "text", "text": {"body": "Price kya hai per gross?"}}]
            }))
            self.assertEqual(len(sent_texts), 1)
            self.assertIn("wholesale volume pricing", sent_texts[0].lower())
            self.assertIn("sales team", sent_texts[0].lower())

    def test_04_buyer_asks_for_ready_stock(self):
        """Test 4: Buyer asks for ready stock -> defer to Sales Team physical godown check."""
        phone = "917777777704"
        sent_texts = []

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)):
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_04", "from": phone, "type": "text", "text": {"body": "Ready stock hai kya?"}}]
            }))
            self.assertEqual(len(sent_texts), 1)
            self.assertIn("warehouse stock verify", sent_texts[0].lower())

    def test_05_buyer_changes_quantity(self):
        """Test 5: Buyer changes quantity (e.g. from 200 to 500 gross) -> acknowledge correction warmly."""
        phone = "917777777705"
        sent_texts = []

        # Seed existing session with 200 Gross
        session = db.get_session_db(phone)
        session["quantity"] = 200
        session["company"] = "Surat Apparels"
        session["city"] = "Surat"
        db.save_session_db(phone, session)

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)):
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_05", "from": phone, "type": "text", "text": {"body": "Nahi, 500 gross kar do"}}]
            }))
            self.assertEqual(len(sent_texts), 1)
            self.assertIn("500 gross", sent_texts[0].lower())
            self.assertIn("update kar diya", sent_texts[0].lower())
            
            # Check DB updated
            re_sess = db.get_session_db(phone)
            self.assertEqual(re_sess["quantity"], 500)

    def test_06_returning_customer_with_existing_details(self):
        """Test 6: Returning customer with known company/city -> does not re-ask company/city."""
        phone = "917777777706"
        sent_texts = []

        # Seed existing customer in DB
        db.save_inquiry_with_photo(
            inquiry_id="INQ-EXISTING-01",
            phone=phone,
            buyer_name="Vikas",
            photo_b64="",
            notes="Previous customer",
            company="Orient Craft",
            city="Noida",
            quantity=100
        )

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)), \
             patch.object(webhook_bot, 'download_whatsapp_media', return_value=DUMMY_JPG):

            # Customer sends new photo with quantity
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Vikas"}}],
                "messages": [{"id": "TEST_HL_06", "from": phone, "type": "image", "image": {"id": "med_06", "caption": "400 gross same chahiye"}}]
            }))
            self.assertEqual(len(sent_texts), 1)
            # Should NOT ask for company or city!
            self.assertNotIn("kripya apni company", sent_texts[0].lower())
            self.assertIn("orient craft", sent_texts[0].lower())

    def test_07_customer_provides_all_details_in_one_message(self):
        """Test 7: Multi-slot all-in-one message -> extracts all facts and avoids repetitive questions."""
        phone = "917777777707"
        sent_texts = []

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)):
            msg_txt = "Hum Apex Fashions Surat se hain, 300 gross River Shell 18L chahiye urgent"
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_07", "from": phone, "type": "text", "text": {"body": msg_txt}}]
            }))
            self.assertEqual(len(sent_texts), 1)
            resp = sent_texts[0].lower()
            self.assertIn("inquiry id:", resp)
            self.assertIn("apex fashions", resp)
            self.assertIn("surat", resp)
            self.assertIn("300 gross", resp)
            self.assertIn("urgent", resp)
            # Does NOT ask for company or quantity
            self.assertNotIn("kripya apni company", resp)

    def test_08_midnight_inquiry_after_hours(self):
        """Test 8: Late night inquiry -> captures details and gives truthful after-hours notice."""
        phone = "917777777708"
        sent_texts = []

        # Mock time to 23:30 IST (18:00 UTC)
        fake_utc = datetime.datetime(2026, 11, 17, 18, 0, 0, tzinfo=datetime.timezone.utc)
        with patch('datetime.datetime') as mock_dt, \
             patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)), \
             patch.object(webhook_bot, 'download_whatsapp_media', return_value=DUMMY_JPG):

            mock_dt.now.return_value = fake_utc
            mock_dt.side_effect = lambda *args, **kwargs: datetime.datetime(*args, **kwargs)

            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_08", "from": phone, "type": "image", "image": {"id": "med_08", "caption": "check buttons"}}]
            }))
            self.assertEqual(len(sent_texts), 1)
            resp = sent_texts[0].lower()
            self.assertIn("office closed", resp)
            self.assertIn("9:30", resp)

    def test_09_customer_requests_similar_samples(self):
        """Test 9: Customer requests similar samples -> flags sample review and coordinates."""
        phone = "917777777709"
        sent_texts = []

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)):
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_09", "from": phone, "type": "text", "text": {"body": "Similar samples dikhao please"}}]
            }))
            self.assertEqual(len(sent_texts), 1)
            self.assertIn("physical samples", sent_texts[0].lower())
            
            sess = db.get_session_db(phone)
            self.assertTrue(sess.get("sample_required"))

    def test_10_customer_asks_for_custom_manufacturing(self):
        """Test 10: Customer asks for custom manufacturing -> explains MOQ 500 Gross, 7-10 days."""
        phone = "917777777710"
        sent_texts = []

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)):
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_10", "from": phone, "type": "text", "text": {"body": "Apna custom design banwana hai"}}]
            }))
            self.assertEqual(len(sent_texts), 1)
            resp = sent_texts[0].lower()
            self.assertIn("custom button manufacturing", resp)
            self.assertIn("500 gross", resp)
            self.assertIn("7-10", resp)

    def test_11_human_salesperson_takes_over(self):
        """Test 11: Human takeover pauses AI replies completely."""
        phone = "917777777711"
        sent_texts = []

        session = db.get_session_db(phone)
        session["human_takeover"] = 1
        db.save_session_db(phone, session)

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)):
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_11", "from": phone, "type": "text", "text": {"body": "Hello are you there?"}}]
            }))
            self.assertEqual(len(sent_texts), 0, "AI must stay 100% silent under human takeover!")

    def test_12_photo_download_failure(self):
        """Test 12: Photo download failure -> honest alert asking buyer to resend, no false claims."""
        phone = "917777777712"
        sent_texts = []

        with patch.object(webhook_bot, 'download_whatsapp_media', side_effect=Exception("Meta network timeout")), \
             patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)):

            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_12", "from": phone, "type": "image", "image": {"id": "med_err", "caption": ""}}]
            }))
            self.assertEqual(len(sent_texts), 1)
            resp = sent_texts[0].lower()
            self.assertIn("download nahi ho paayi", resp)
            self.assertIn("dobara bhej", resp)

    def test_13_crm_save_failure_recovery(self):
        """Test 13: CRM save failure is handled gracefully without crashing the webhook handler."""
        phone = "917777777713"
        sent_texts = []

        with patch.object(db, 'save_inquiry_with_photo', side_effect=Exception("Database lock error")), \
             patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)):

            # Should not crash the process
            try:
                asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                    "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                    "messages": [{"id": "TEST_HL_13", "from": phone, "type": "text", "text": {"body": "Hum Apex Fashions Surat se hain, 300 gross River Shell 18L chahiye"}}]
                }))
            except Exception as e:
                self.fail(f"Webhook process crashed on CRM save failure: {e}")

    def test_14_duplicate_whatsapp_webhook_delivery(self):
        """Test 14: Duplicate webhook delivery is caught by idempotency without duplicate messages."""
        phone = "917777777714"
        sent_texts = []

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)):
            msg_payload = {
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_14_DUP", "from": phone, "type": "text", "text": {"body": "Hi"}}]
            }
            # First delivery
            asyncio.run(webhook_bot.process_incoming_whatsapp_message(msg_payload))
            self.assertEqual(len(sent_texts), 1)

            # Duplicate delivery of exact same message ID
            asyncio.run(webhook_bot.process_incoming_whatsapp_message(msg_payload))
            self.assertEqual(len(sent_texts), 1, "Duplicate message ID must NOT trigger a second reply!")

    def test_15_buyer_stops_replying_and_returns_later(self):
        """Test 15: Buyer stops replying midway, returns later -> resumes conversation seamlessly."""
        phone = "917777777715"
        sent_texts = []

        with patch.object(webhook_bot, 'send_whatsapp_text', side_effect=lambda to, txt, *a, **kw: sent_texts.append(txt)), \
             patch.object(webhook_bot, 'download_whatsapp_media', return_value=DUMMY_JPG):

            # Turn 1: Buyer sends photo, bot asks quantity
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_15_1", "from": phone, "type": "image", "image": {"id": "med_15", "caption": ""}}]
            }))
            self.assertIn("inquiry id:", sent_texts[-1].lower())
            
            # Buyer disappears for hours/days... Session persists in SQLite!
            sess = db.get_session_db(phone)
            saved_inq_id = sess.get("active_inquiry_id")
            self.assertTrue(saved_inq_id)

            # Turn 2: Buyer returns and says "sorry busy tha, 400 gross chahiye"
            asyncio.run(webhook_bot.process_incoming_whatsapp_message({
                "contacts": [{"wa_id": phone, "profile": {"name": "Buyer"}}],
                "messages": [{"id": "TEST_HL_15_2", "from": phone, "type": "text", "text": {"body": "sorry busy tha, 400 gross chahiye"}}]
            }))
            # Bot remembers active inquiry and asks for company/city
            self.assertIn("400 gross", sent_texts[-1].lower())
            self.assertIn("company", sent_texts[-1].lower())

if __name__ == "__main__":
    unittest.main()
