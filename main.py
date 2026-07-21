# ไฟล์: main.py
import os
import sys
import requests  # ใช้แทน pyodbc สำหรับการสื่อสารผ่าน Network
import threading
from kivy.clock import Clock
from datetime import datetime
from kivymd.app import MDApp
from kivy.lang import Builder
from kivy.core.text import LabelBase
from kivy.utils import platform
from kivy.core.window import Window
from kivymd.uix.screen import MDScreen
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.menu import MDDropdownMenu # อย่าลืมบรรทัดนี้ที่ด้านบน
from kivy.properties import StringProperty

# รองรับระบบเสียงบน Android
APP_VERSION = "1.2"
if platform == 'android':
    from jnius import autoclass, PythonJavaClass, java_method
    winsound = None
elif platform == 'win':
    import winsound
else:
    # BUGFIX: เดิม `import winsound` แบบไม่มีเงื่อนไข ทำให้แอปพังทันทีตอนเปิด
    # ถ้ารันบน Linux/macOS (เช่นตอนพัฒนา) เพราะโมดูล winsound มีเฉพาะบน Windows
    winsound = None

Window.keyboard_anim_delay = 0

from database import (
    init_db, save_config, 
    get_config, 
    import_products_from_mssql,
    query_product, 
    insert_scan_result_to_db, 
    get_recent_scans_from_table,
    query_product_by_code,
    get_existing_scan,
    update_scan_qty,
    save_edit_qty,
    get_export_rows,
    clear_scan_table,
    get_connection
)

# BUGFIX: เดิมใช้ `__file__ in locals()` ซึ่งเช็คผิด (เช็คว่าค่าของ __file__ เป็น "คีย์"
# อยู่ใน dict locals() หรือไม่ ซึ่งไม่มีความหมายตามที่ตั้งใจ) เปลี่ยนมาใช้ try/except แทน
try:
    CUR_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    CUR_DIR = os.getcwd()

class InventoryApp(MDApp):
    dialog = None
    version = StringProperty(APP_VERSION)
    def build(self):
        if platform == 'android':
            from jnius import autoclass
            ActivityInfo = autoclass('android.content.pm.ActivityInfo')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity
            activity.setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT)
        
        # 2. ป้องกันคีย์บอร์ดดันหน้าจอ (Pan mode)
            Window.softinput_mode='below_target'
        #Window.softinput_mode='resize'
        
        init_db() 
        self.theme_cls.theme_style = "Light"
        self.theme_cls.primary_palette = "Orange"
        self.theme_cls.material_design_icons = "font"
        font_path = os.path.join(CUR_DIR, "fonts", "Kanit-Regular.ttf")
        if not os.path.exists(font_path):
            font_path = os.path.join(CUR_DIR, "Kanit-Regular.ttf")

        try:
            LabelBase.register(name="ThaiFont", fn_regular=font_path)
            for style in list(self.theme_cls.font_styles.keys()):
                if style not in ["Icons"]:
                    self.theme_cls.font_styles[style] = [
                    "ThaiFont",
                    self.theme_cls.font_styles[style][1],
                    self.theme_cls.font_styles[style][2],
                    self.theme_cls.font_styles[style][3]
                ] # <--- ต้องมี ] ปิดตรงนี้ด้วย
        except Exception as e:
            print(f"Font Error: {e}")

        kv_path = os.path.join(CUR_DIR, "main_design.kv")
        return Builder.load_file(kv_path)

    def show_alert(self, title, text):
        if self.dialog:
            self.dialog.dismiss()

        self.dialog = MDDialog(
            title=title,
            text=text,
            buttons=[MDRaisedButton(text="ตกลง", font_name="ThaiFont", on_release=lambda x: self.dialog.dismiss())]
        )
        self.dialog.open()

class MainMenuScreen(MDScreen):
    def exit_app(self):
        sys.exit(0)

class ConfigScreen(MDScreen):
    def go_back(self):
        self.manager.current = 'menu_screen'
    def __init__(self, **kw):
        super().__init__(**kw)
        self.menu = None
        self.current_selected_config = {}
    def on_enter(self):
        """โหลดข้อมูลอัตโนมัติเมื่อเข้าหน้านี้"""
        # ดึงข้อมูลจากฐานข้อมูล SQLite
        config = get_config() 
        
        # ถ้าไม่มีข้อมูลใน DB ให้ข้ามไป (ไม่ต้องโชว์อะไร)
        if not config:
            return

        # config คือ tuple ตามลำดับในฐานข้อมูลของคุณ:
        # (branch_name, db_server_ip, db_name, db_user, db_password, count_month, iis_server_ip)
        
        # 1. อัปเดต Label บน UI
        self.ids.lbl_branch_name.text = f"สาขา: {config[0]}"
        self.ids.lbl_db_ip.text = f"DB Server IP: {config[1]}"
        self.ids.lbl_db_name.text = f"DB Name: {config[2]}"
        self.ids.lbl_month.text = f"เดือน: {config[5]}"
        
        # 2. อัปเดต Input Field และ Dropdown
        self.ids.drop_branch.text = config[0]
        self.ids.txt_iis_ip.text = config[6]
        
        # 3. เก็บข้อมูลไว้ในตัวแปรสำหรับใช้งานต่อ (เช่น ตอนกดปุ่ม Save หรือ Test)
        self.current_selected_config = {
            'branch_name': config[0],
            'db_server_ip': config[1],
            'db_name': config[2],
            'db_user': config[3],
            'db_password': config[4],
            'count_month': config[5],
            'iis_server_ip': config[6]
        }
    def fetch_config_from_iis(self):
        """ดึงข้อมูล Config จาก IIS และแสดงรายการสาขา"""

        iis_ip = self.ids.txt_iis_ip.text.strip()

        if not iis_ip:
            MDApp.get_running_app().show_alert("⚠️", "กรุณากรอก IP ของ IIS ก่อน")
            return

        # ปิด Dropdown เดิมก่อน (ถ้ามี)
        if self.menu:
            try:
                self.menu.dismiss()
            except Exception:
                pass
            self.menu = None

        try:
            url = f"http://{iis_ip}/API_HWK_CountStock_Data/get_config.ashx"

            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()

            if not data:
                MDApp.get_running_app().show_alert("⚠️", "ไม่พบข้อมูล Config")
                return

            menu_items = []

            for item in data:
                menu_items.append(
                    {
                        "text": item["branch_name"],
                        "viewclass": "OneLineListItem",
                        "on_release": lambda x=item: self.select_branch(x)
                    }
                )

            self.menu = MDDropdownMenu(
                caller=self.ids.drop_branch,
                items=menu_items,
                width_mult=4
            )

            self.menu.open()

        except requests.exceptions.RequestException as e:
            MDApp.get_running_app().show_alert(
                "❌ Error",
                f"ไม่สามารถเชื่อมต่อ Server ได้\n{e}"
            )

        except Exception as e:
            MDApp.get_running_app().show_alert(
                "❌ Error",
                f"ไม่สามารถดึง Config\n{e}"
        )

    def select_branch(self, item):
        """เมื่อเลือกสาขา"""
        self.current_selected_config = item

        self.ids.drop_branch.text = item["branch_name"]

        self.ids.lbl_branch_name.text = f"สาขา: {item['branch_name']}"
        self.ids.lbl_db_ip.text = f"DB Server IP: {item['db_server_ip']}"
        self.ids.lbl_db_name.text = f"DB Name: {item['db_name']}"
        self.ids.lbl_month.text = f"เดือน: {item['count_month']}"

        if self.menu:
            try:
                self.menu.dismiss()
            except Exception:
                pass

    def save_data(self):
        """3. บันทึกลง SQLite"""
        c = self.current_selected_config
        if not c:
            MDApp.get_running_app().show_alert("⚠️", "กรุณา Get Config และเลือกสาขาก่อนบันทึก")
            return
        
        try:
            # ดึงค่าจากตัวแปร current_selected_config
            save_config(
                c['branch_name'], c['db_server_ip'], c['db_name'], 
                c['db_user'], c['db_password'], c['count_month'], self.ids.txt_iis_ip.text.strip()
            )
            MDApp.get_running_app().show_alert("✓ สำเร็จ", "บันทึกค่าลงฐานข้อมูลเรียบร้อยแล้ว")
        except Exception as e:
            MDApp.get_running_app().show_alert("❌ Error", f"ไม่สามารถบันทึก: {e}")

    def test_all_connections(self):
        """ทดสอบเชื่อมต่อ"""
        c = self.current_selected_config
        if not c:
            MDApp.get_running_app().show_alert("⚠️", "กรุณาเลือกสาขาก่อนทดสอบ")
            return
        
        # ส่งค่าไปทดสอบผ่าน IIS
        try:
            payload = {'action': 'test_connection', 'db_server_ip': c['db_server_ip'], 'db_name': c['db_name']}
            response = requests.post(f"http://{c['iis_server_ip']}/API_HWK_CountStock_Data/Export.ashx", json=payload, timeout=10)
            if response.status_code == 200:
                MDApp.get_running_app().show_alert("✅ สำเร็จ", "การเชื่อมต่อปกติ")
            else:
                MDApp.get_running_app().show_alert("❌ ล้มเหลว", "เข้า DB ไม่ได้")
        except Exception as e:
            MDApp.get_running_app().show_alert("❌ Error", f"{e}")


class ImportScreen(MDScreen):
    
    def go_back(self):
        self.manager.current = 'menu_screen'

    def start_import(self):
        # 1. ปิดปุ่ม
        self.ids.btn_import.disabled = True
        
        # 2. เริ่ม Thread
        threading.Thread(target=self.run_import_thread, daemon=True).start()

    def run_import_thread(self):
        # BUGFIX: เดิมถ้า import_products_from_mssql() throw exception ตรงๆ
        # (ไม่ใช่ return ค่า error กลับมา) จะทำให้ thread ตายเงียบๆ ปุ่ม Import
        # จะค้าง disabled อยู่ตลอดและผู้ใช้ไม่เห็น error ใดๆ เลย
        try:
            result = import_products_from_mssql()
        except Exception as e:
            result = str(e)

        # ส่งผลลัพธ์กลับไปที่ Main Thread เพื่ออัปเดต UI
        Clock.schedule_once(lambda dt: self.show_import_result(result))

    def show_import_result(self, result):
        # 3. เปิดปุ่มคืน
        self.ids.btn_import.disabled = False
        
        # 4. แสดงผลลัพธ์
        if isinstance(result, int):
            if result > 0:
                MDApp.get_running_app().show_alert("✅ สำเร็จ", f"ซิงค์และแทนที่สินค้าแล้ว {result:,} รายการ")
            else:
                MDApp.get_running_app().show_alert("⚠️ แจ้งเตือน", "ไม่พบข้อมูลสินค้า")
        else:
            MDApp.get_running_app().show_alert("❌ ล้มเหลว", str(result))
   

class StockCountScreen(MDScreen):
    edit_dialog = None
    edit_text_field = None

    def on_enter(self):
        Clock.schedule_once(
            lambda dt: self.force_focus(),
            0.3
        )

        self.update_recent_list()

    def go_back(self):
        self.stop_android_scanner()
        self.manager.current = 'menu_screen'

    def force_focus(self):
        # BUGFIX: เดิมตรงนี้เคยเรียก Window.release_keyboard() ต่อท้ายด้วย ทำให้
        # เกิดวงจรเปิด-ปิด soft keyboard ซ้อนกับการ toggle focus False->True
        # วงจรนี้ไม่เสถียรบนเครื่อง Newland จริง ทำให้ตัวอักษรที่ scanner ยิงเข้ามา
        # หลุดหายบางส่วน และ widget เสีย focus ไปเฉยๆ (cursor ไม่กลับมาที่ช่องยิง)
        # ตัด Window.release_keyboard() ออก เหลือแค่ toggle focus เฉยๆ ก็พอ
        self.ids.txt_barcode.focus = False

        def do_focus(dt):
            self.ids.txt_barcode.focus = True

        Clock.schedule_once(do_focus, 0.1)

    def on_barcode_input(self):
        barcode = self.ids.txt_barcode.text.strip()

        if not barcode:
            return

        print("TEXTFIELD BARCODE =", barcode)

        self.process_barcode(barcode)

        self.ids.txt_barcode.text = ""

        Clock.schedule_once(
            lambda dt: self.force_focus(),
            0.05
        )

    '''  def start_android_scanner(self):

        if platform != "android":
            return

        if hasattr(self, "receiver"):
            return

        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            IntentFilter = autoclass("android.content.IntentFilter")

            receiver = create_android_receiver(
                self.on_android_barcode_received
            )

            activity = PythonActivity.mActivity

            actions = [
                "nlscan.action.SCANNER_RESULT",      # Newland
                "com.cipherlab.barcode.queue"        # CipherLab
            ]

            # BUGFIX: เดิมตั้ง self.receiver ก่อนวน registerReceiver ถ้าตัวใดตัวหนึ่ง
            # ลงทะเบียนไม่สำเร็จ (exception) hasattr(self, "receiver") ด้านบนจะ True
            # อยู่ดี ทำให้ครั้งต่อไปที่เข้าหน้านี้จะไม่พยายามลงทะเบียนซ้ำอีกเลย
            registered_any = False
            for action in actions:
                try:
                    activity.registerReceiver(receiver, IntentFilter(action))
                    registered_any = True
                except Exception as reg_err:
                    print(f"Register {action} failed: {reg_err}")

            if registered_any:
                self.receiver = receiver
                print("Scanner Receiver Ready")

        except Exception as e:
            print(e)
    ''' 
    def stop_android_scanner(self):
    
        """ปิดระบบดักจับเมื่อออกจากหน้าสแกน"""

        if platform == 'android' and hasattr(self, 'receiver'):

            try:

                PythonActivity = autoclass('org.kivy.android.PythonActivity')

                current_activity = PythonActivity.mActivity

                current_activity.unregisterReceiver(self.receiver)

                del self.receiver

            except Exception as e:

                print(f"Stop Scanner Error: {e}")
                
    def play_sound(self, success=True):
        """ระบบเล่นเสียงแจ้งเตือน"""
        if platform == 'android':
            try:
                ToneGenerator = autoclass('android.media.ToneGenerator')
                AudioManager = autoclass('android.media.AudioManager')
                # 100 = ความดังสูงสุด
                tone_gen = ToneGenerator(AudioManager.STREAM_MUSIC, 100)
                if success:
                    # เสียงติ๊ดสั้น (ยิงสำเร็จ)
                    tone_gen.startTone(ToneGenerator.TONE_PROP_BEEP, 150)
                else:
                    # เสียงตื๊ดยาวเตือน (ยิงผิดพลาด/ไม่พบสินค้า)
                    tone_gen.startTone(ToneGenerator.TONE_SUP_ERROR, 400)
            except Exception as e:
                print(f"Sound Error: {e}")
        elif winsound is not None:
            # เล่นเสียงบี๊บบน Windows สำหรับทดสอบพัฒนา
            if success:
                winsound.Beep(2000, 150)
            else:
                winsound.Beep(600, 400)
        # BUGFIX: ถ้าไม่ใช่ android และไม่ใช่ windows (เช่น mac/linux dev) ให้ข้ามไปเงียบๆ
        # แทนที่จะพยายามเรียก winsound ที่ import ไม่สำเร็จแล้วทำให้แอปพัง

    def on_android_barcode_received(self, barcode_str):
        """รับค่าบาร์โค้ดจากหัวอ่าน CipherLab ส่งมาทำงานต่อ"""
        print("SCAN RECEIVE =", barcode_str)
        self.process_barcode(barcode_str)

    def process_barcode(self, barcode):
        """ฟังก์ชันหลักในการตรวจสอบและบันทึกข้อมูล"""
        print("PROCESS =", barcode)
        barcode_input = barcode.strip()
        location = self.ids.txt_location.text.strip()
        staff = self.ids.txt_staff.text.strip()
        
        # 1. ตรวจสอบข้อมูลเบื้องต้น
        if not location or not staff:
            self.play_sound(success=False)
            MDApp.get_running_app().show_alert("⚠️ คำเตือน", "กรุณาระบุตำแหน่งและผู้ตรวจนับ")
            self.reset_scan_field()
            return
            
        # 2. ค้นหาจากบาร์โค้ดก่อน (ตามฟังก์ชันเดิมของคุณ)
        product = query_product(barcode_input) 
        
        # 3. ถ้าหาจากบาร์โค้ดไม่พบ ให้ลองหาจาก รหัสสินค้า (Product Code)
        if not product:
    
             product = query_product_by_code(barcode_input)
            
        # 4. ถ้าหาไม่เจอทั้ง 2 อย่าง ให้แจ้งเตือน
        if not product:
            self.play_sound(success=False)
            MDApp.get_running_app().show_alert("❌ ไม่พบข้อมูล", f"ไม่พบสินค้า [{barcode_input}] ในระบบ")
            self.reset_scan_field()
            return

        # 5. หากพบสินค้า (ไม่ว่าจะมาจากบาร์โค้ดหรือรหัสสินค้า) ให้บันทึกข้อมูล
        product_code, product_name, unit_name = product
        
        # ส่วนบันทึกลง DB ตามโค้ดเดิมของคุณ
        try:

            row = get_existing_scan(location, barcode_input)

            if row:

                scan_id, current_qty = row

                new_qty = current_qty + 1

                update_scan_qty(scan_id, new_qty)

                self.ids.lbl_product_code.text = f"รหัส: {product_code}"
                self.ids.lbl_product_name.text = f"✓ [ยิงซ้ำ +1] รวม: {new_qty} {unit_name}"
                self.ids.lbl_unit.text = f"หน่วย: {unit_name}"

            else:

                insert_scan_result_to_db(
                    location,
                    staff,
                    product_code,
                    barcode_input,
                    1
                )

                self.ids.lbl_product_code.text = f"รหัส: {product_code}"
                self.ids.lbl_product_name.text = f"ชื่อสินค้า: {product_name}"
                self.ids.lbl_unit.text = f"หน่วย: {unit_name}"

            self.play_sound(success=True)

        except Exception as e:
            # BUGFIX: เดิม except นี้แค่ print(e) เฉยๆ แล้วปล่อยให้โค้ดไหลต่อไปเคลียร์
            # ช่อง barcode เหมือนบันทึกสำเร็จ ทำให้ผู้ใช้ไม่รู้เลยว่าจริงๆ แล้ว
            # "ข้อมูลไม่ถูกบันทึกลง DB" ตอนนี้จะแจ้งเตือนผู้ใช้ด้วย และหยุดไม่ทำต่อ
            print(f"Error Saving Scan: {e}")
            self.play_sound(success=False)
            MDApp.get_running_app().show_alert(
                "❌ บันทึกไม่สำเร็จ",
                f"เกิดข้อผิดพลาดขณะบันทึกข้อมูล กรุณาลองใหม่\n{e}"
            )
            self.reset_scan_field()
            return

        # เคลียร์ช่อง Barcode และดึง cursor กลับไปพร้อมยิงครั้งถัดไปทันที
        # BUGFIX: เดิมตั้ง focus = True แบบทันที (synchronous) ก่อน แล้วค่อยเรียก
        # update_recent_list() ทีหลัง ซึ่งฟังก์ชันนั้น clear_widgets()/สร้าง list
        # ใหม่ทั้งหมด ทำให้ widget tree เปลี่ยนและไป "แย่ง" focus คืนจาก txt_barcode
        # โดยเฉพาะบน Android (CipherLab RK25 / Newland MT67) ทำให้ cursor ไม่กลับไป
        # ที่ช่องบาร์โค้ดพร้อมสำหรับการยิงครั้งถัดไปจริง แก้โดย:
        #   1. อัปเดตลิสต์ล่าสุดให้เสร็จก่อน (widget tree นิ่งแล้ว)
        #   2. เคลียร์ข้อความ
        #   3. ใช้ force_focus() ซึ่ง toggle focus False -> True ผ่าน Clock delay
        #      (pattern เดียวกับที่ on_windows_keyboard_validate ใช้อยู่แล้ว)
        self.ids.txt_barcode.text = ""
        self.update_recent_list()


    def reset_scan_field(self):
        # BUGFIX: เดิมฟังก์ชันนี้ถูกคอมเมนต์ทิ้งไว้ทั้งหมด แต่โค้ดด้านบนยังเรียก
        # self.reset_scan_field() อยู่ 2 จุด (กรณีไม่กรอกตำแหน่ง/ผู้ตรวจนับ และกรณี
        # ไม่พบสินค้า) ทำให้เกิด AttributeError แอปค้าง/พังทุกครั้งที่เจอ 2 เคสนี้
        self.ids.txt_barcode.text = ""
        self.ids.txt_barcode.focus = False

        Clock.schedule_once(
            lambda dt: setattr(self.ids.txt_barcode, "focus", True),
            0.05
        )

        self.update_recent_list()

    def update_recent_list(self):
        self.ids.list_recent_scans.clear_widgets()
        from kivy.factory import Factory
        
        recent_data = get_recent_scans_from_table(limit=5)
        for row in recent_data:
            b_code = row[0]
            p_name = row[1] if row[1] else "Barcode ไม่ถูกต้อง สแกนรหัสสินค้าแทนแล้ว"
            quantity = row[2]
            s_date = row[3] if row[3] else "-"
            location=row[4]
            
            item_text = f"{p_name} (จำนวน: {quantity}) ✏️"
            item_secondary = f"บาร์โค้ด: {b_code} | เวลาสแกน: {s_date}"
            
            list_item = Factory.ThaiTwoLineListItem(text=item_text, secondary_text=item_secondary)
            list_item.bind(on_release=lambda x, b=b_code, q=quantity, l=location, n=p_name: self.open_edit_dialog(b, q, l, n))
            self.ids.list_recent_scans.add_widget(list_item)

    def open_edit_dialog(self, barcode, current_qty, location, product_name):
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.label import MDLabel

        dialog_layout = MDBoxLayout(orientation="vertical", spacing="12dp", size_hint_y=None, height="140dp")
        lbl_title = MDLabel(text=f"แก้ไขจำนวน: {product_name}", font_name="ThaiFont", font_style="Subtitle1", size_hint_y=None, height="40dp")
        self.edit_text_field = MDTextField(text=str(current_qty), input_filter="int", hint_text="Edit QTY", font_name="ThaiFont", size_hint_y=None, height="50dp")
        dialog_layout.add_widget(lbl_title)
        dialog_layout.add_widget(self.edit_text_field)
        
        self.current_edit_data = {"barcode": barcode, "location": location}
        btn_cancel = MDFlatButton(text="ยกเลิก", font_name="ThaiFont")
        btn_save = MDRaisedButton(text="บันทึก", font_name="ThaiFont")
        btn_cancel.bind(on_release=lambda x: self.edit_dialog.dismiss())
        btn_save.bind(on_release=lambda x: self.save_edited_qty())

        self.edit_dialog = MDDialog(type="custom", content_cls=dialog_layout, buttons=[btn_cancel, btn_save])
        self.edit_dialog.open()

    def save_edited_qty(self):
        new_qty_text = self.edit_text_field.text.strip()
        if not new_qty_text: return
            
        try:
            new_qty = int(new_qty_text)

            save_edit_qty(
                self.current_edit_data["location"],
                self.current_edit_data["barcode"],
                new_qty
            )

        except Exception as e:
            # BUGFIX: เดิม except นี้แค่ print(e) แล้วปิด dialog ต่อเหมือนบันทึกสำเร็จ
            # ทำให้ผู้ใช้ไม่รู้ว่าการแก้ไขจำนวนไม่ถูกบันทึกจริง เพิ่ม alert แจ้งเตือน
            print(f"Error Editing Qty: {e}")
            self.edit_dialog.dismiss()
            MDApp.get_running_app().show_alert("❌ Error", f"ไม่สามารถบันทึกจำนวนที่แก้ไข: {e}")
            self.update_recent_list()
            return
            
        self.edit_dialog.dismiss()
        self.update_recent_list()

class ExportScreen(MDScreen):
    confirm_clear_dialog = None

    def go_back(self):
        self.manager.current = 'menu_screen'

    def export_data(self, target_server_table):
        config = get_config()
        if not config:
            MDApp.get_running_app().show_alert("❌ ข้อผิดพลาด", "ไม่พบข้อมูลการตั้งค่า")
            return
            
        iis_ip = config[6] # ดึงเฉพาะ IP ของ Server
        db_name = config[2]    # ชื่อ Database ที่ตั้งค่าไว้ในหน้าจอ Config
        
        # ดึงข้อมูลจาก SQLite ในเครื่อง
        rows = get_export_rows()
        #lite_conn.close()
        
        if not rows:
            MDApp.get_running_app().show_alert("⚠️ ไม่มีข้อมูล", "ไม่พบรายการค้างส่ง")
            return

        # แปลงข้อมูลเป็น List of Dictionaries เพื่อส่งผ่าน JSON
        current_time = datetime.now().strftime('%Y/%m/%d')
        data_to_send = [
            {'location': r[0], 'staff': r[1], 'p_code': r[2], 'barcode': r[3], 'qty': r[4], 'date': r[5],'export_date': current_time} 
            for r in rows
        ]
       
        
        payload = {
        'table': target_server_table, 
        'db_server_ip': config[1], # db_server_ip ที่ดึงมาจาก SQLite
        'db_name': config[2], 
        'data': data_to_send
    }
        # ส่งผ่าน API ไปที่ IIS ที่ไฟล์ Export.ashx
        try:
            # ใช้ iis_ip ที่ดึงมาจากฐานข้อมูล
            url = f"http://{iis_ip}/API_HWK_CountStock_Data/Export.ashx" 
            
            response = requests.post(url, json=payload, timeout=300)
            
            if response.status_code == 200:
                self.show_export_success_dialog(target_server_table, len(rows))
            else:
                 # เพิ่มการตรวจจับข้อความ Error ที่เราส่งมาจาก C#
                error_msg = response.text
                if "SQL_ERROR:" in error_msg:
                    # ตัดเอาเฉพาะข้อความหลัง SQL_ERROR: มาโชว์
                    clean_msg = error_msg.split("SQL_ERROR:")[1].strip()
                    MDApp.get_running_app().show_alert("❌ Server Error", clean_msg)
                else:
                    # ถ้าไม่ใช่ Error จาก SQL ให้โชว์ Error ปกติ
                    MDApp.get_running_app().show_alert("❌ ส่งออกล้มเหลว", "เกิดข้อผิดพลาดที่ Server")
        except Exception as e:
            MDApp.get_running_app().show_alert("❌ เชื่อมต่อไม่ได้", f"ตรวจสอบ IP Server ({iis_ip}): {e}")
            
    def show_export_success_dialog(self, table_name, record_count):
        btn_no = MDFlatButton(text="เก็บข้อมูลไว้ก่อน", font_name="ThaiFont")
        btn_yes = MDRaisedButton(text="ยืนยัน ลบข้อมูลในเครื่อง", font_name="ThaiFont", md_bg_color=[0.8, 0.2, 0.2, 1])
        btn_no.bind(on_release=lambda x: self.confirm_clear_dialog.dismiss())
        btn_yes.bind(on_release=lambda x: self.clear_pda_table())

        self.confirm_clear_dialog = MDDialog(
            title="✅ ส่งออกข้อมูลครบถ้วนสมบูรณ์",
            text=f"ส่งข้อมูลไปยังตาราง {table_name} บนเซิร์ฟเวอร์ครบทั้ง {record_count:,} รายการแล้ว\n\nต้องการลบข้อมูลชุดนี้ออกจากเครื่อง PDA หรือไม่?",
            buttons=[btn_no, btn_yes]
        )
        self.confirm_clear_dialog.open()

    def clear_pda_table(self):
    
        try:
            clear_scan_table()

            # ปิด Dialog
            if self.confirm_clear_dialog:
                self.confirm_clear_dialog.dismiss()

            # แจ้งผล
            MDApp.get_running_app().show_alert(
                "✅ สำเร็จ",
                "ล้างข้อมูลการสแกนในเครื่องเรียบร้อยแล้ว"
            )

            # Refresh รายการบนหน้าจอ (ถ้ามี)
            if hasattr(self, "update_recent_list"):
                self.update_recent_list()

        except Exception as e:

            if self.confirm_clear_dialog:
                self.confirm_clear_dialog.dismiss()

            MDApp.get_running_app().show_alert(
                "❌ Error",
                f"ไม่สามารถล้างข้อมูลได้\n{e}"
            )
                
    def show_confirm_clear_dialog(self):
        self.confirm_clear_dialog = MDDialog(
            title="⚠️ ยืนยันการล้างข้อมูล",
            text="คุณต้องการลบข้อมูลการสแกนทั้งหมดออกจากเครื่องใช่หรือไม่?",
            buttons=[
                MDFlatButton(text="ยกเลิก", on_release=lambda x: self.confirm_clear_dialog.dismiss()),
                MDRaisedButton(text="ลบข้อมูล", md_bg_color=[0.8, 0.2, 0.2, 1], on_release=lambda x: self.clear_pda_table()),
            ],
        )
        self.confirm_clear_dialog.open()

# --- โครงสร้างเชื่อมต่อ Java Class สำหรับการทำงานแบบ Background Intent Receiver ---
''' def create_android_receiver(callback):
    
    if platform != "android":
        return None

    class AndroidBarcodeReceiver(PythonJavaClass):

        __javainterfaces__ = ['android/content/BroadcastReceiver']
        __javacontext__ = 'app'

        def __init__(self, cb):
            super().__init__()
            self.cb = cb

        @java_method("(Landroid/content/Context;Landroid/content/Intent;)V")
        def onReceive(self, context, intent):

            barcode = None

            keys = [

                # Newland
                "SCAN_BARCODE1",
                "scan_result",

                # CipherLab
                "com.cipherlab.barcode.queue_string",

                # Generic
                "barcode",
                "barcode_string",
                "decode_data",
                "scannerdata",
                "data"

            ]

            for key in keys:
                try:
                    barcode = intent.getStringExtra(key)
                    if barcode:
                        break
                except Exception:
                    pass

            if barcode:
                Clock.schedule_once(
                    lambda dt: self.cb(barcode.strip()),
                    0
                )

    return AndroidBarcodeReceiver(callback)
 '''
    
if __name__ == "__main__":
    Window.size = (380, 680)
    InventoryApp().run()