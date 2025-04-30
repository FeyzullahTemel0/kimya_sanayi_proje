import hashlib
import time
import datetime
import csv
import os
import customtkinter as ctk
from pymodbus.client import ModbusTcpClient
import pyperclip
import threading

# ------------------ Kullanıcı Aktivite Kaydı (user_activity.csv) ------------------ #
def log_user_activity(username, action, usage_time=0):
    """Kullanıcı aktivitelerini user_activity.csv dosyasına kaydeder."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("user_activity.csv", mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([now_str, username, action, f"{usage_time:.2f}"])


# ------------------ CSV İşlemleri ------------------ #
def load_users_csv(filepath="users.csv"):
    if not os.path.exists(filepath):
        return None
    user_db = {}
    with open(filepath, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 7:
                continue
            uname, pw, role, define, apply, list_, user_mgmt = row
            user_db[uname] = {
                "password": pw,
                "role": role,
                "permissions": {
                    "define": (define == "True"),
                    "apply": (apply == "True"),
                    "list": (list_ == "True"),
                    "user_mgmt": (user_mgmt == "True")
                }
            }
    return user_db

def save_users_csv(user_db, filepath="users.csv"):
    with open(filepath, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for uname, data in user_db.items():
            pw = data["password"]
            role = data["role"]
            define = data["permissions"]["define"]
            apply_ = data["permissions"]["apply"]
            list_ = data["permissions"]["list"]
            user_mgmt = data["permissions"]["user_mgmt"]
            writer.writerow([uname, pw, role, define, apply_, list_, user_mgmt])


def load_recipes_csv(filepath="recipes.csv"):
    """
    Yeni sütun eklenmiştir: Mikser süresi (mixer_time).
    Format: name, code, amounts_str, used_str, duration_str, mixer_str
    """
    if not os.path.exists(filepath):
        return []
    recipe_list = []
    with open(filepath, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            # En az 6 sütun bekleniyor
            if len(row) < 6:
                continue
            name, code, amounts_str, used_str, duration_str, mixer_str = row
            if amounts_str.strip():
                amounts = [float(x) for x in amounts_str.split(";")]
            else:
                amounts = []
            used = (used_str == "True")
            duration = float(duration_str) if duration_str else None
            mixer_time = float(mixer_str) if mixer_str else 0.0

            recipe_list.append({
                "name": name,
                "code": code,
                "amounts": amounts,
                "used": used,
                "duration": duration,
                "mixer_time": mixer_time
            })
    return recipe_list

def save_recipes_csv(recipe_list, filepath="recipes.csv"):
    """
    Format: name, code, amounts_str, used_str, duration_str, mixer_str
    """
    with open(filepath, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for recipe in recipe_list:
            name = recipe["name"]
            code = recipe["code"]
            amounts_str = ";".join([str(x) for x in recipe["amounts"]])
            used_str = str(recipe["used"])
            duration_str = str(recipe["duration"] if recipe["duration"] else "")
            mixer_str = str(recipe.get("mixer_time", 0.0))
            writer.writerow([name, code, amounts_str, used_str, duration_str, mixer_str])


# ------------------ İş Mantığı: RecipeManager & Motor ------------------ #
class RecipeManager:
    def __init__(self, plc_ip='localhost', plc_port=502, secret_key="Feyzullah_Temel"):
        self.plc_ip = plc_ip
        self.plc_port = plc_port
        self.secret_key = secret_key
        self.recipe_list = load_recipes_csv("recipes.csv")

        # Malzeme isimleri
        self.material_names = ["Reçine", "AKAP110", "AKKOM DCB", "Aseton", "Butil Asetat"]

        # PLC ile ilgili sabitler
        self.silo_addresses = [10, 11, 12, 13, 14]
        self.motor_start_address = 11
        self.motor_stop_address = 12
        self.terazi_address = 2

    def create_recipe_code(self, ingredient_amounts):
        hash_input = ''.join(map(lambda x: f"{x:.3f}", ingredient_amounts)) + self.secret_key
        return hashlib.sha256(hash_input.encode()).hexdigest()[:11]

    def decode_recipe_code(self, recipe_code):
        for recipe in self.recipe_list:
            if recipe["code"] == recipe_code:
                return recipe["amounts"]
        return None

    def add_recipe(self, name, code, amounts, mixer_time=0.0):
        # Aynı isimde reçete var mı kontrolü
        if any(r["name"] == name for r in self.recipe_list):
            raise ValueError(f"'{name}' isminde bir reçete zaten var!")
        self.recipe_list.append({
            "name": name,
            "code": code,
            "amounts": amounts,
            "used": False,
            "duration": None,
            "mixer_time": mixer_time
        })
        save_recipes_csv(self.recipe_list)

    def update_recipe(self, old_recipe, new_name, new_amounts):
        # İsim çakışması kontrolü
        for r in self.recipe_list:
            if r is old_recipe:
                continue
            if r["name"] == new_name:
                raise ValueError(f"'{new_name}' isminde bir reçete zaten var!")
        old_recipe["name"] = new_name
        old_recipe["amounts"] = new_amounts
        save_recipes_csv(self.recipe_list)

    def remove_recipe(self, recipe):
        self.recipe_list.remove(recipe)
        save_recipes_csv(self.recipe_list)

    def update_recipe_status(self, recipe_code, used=True, duration=None):
        for recipe in self.recipe_list:
            if recipe["code"] == recipe_code:
                recipe["used"] = used
                if duration is not None:
                    recipe["duration"] = duration
                break
        save_recipes_csv(self.recipe_list)

    def get_mixer_time(self, recipe_code):
        """Reçetenin mikser süresini döndürür (yoksa 0.0)."""
        for recipe in self.recipe_list:
            if recipe["code"] == recipe_code:
                return recipe.get("mixer_time", 0.0)
        return 0.0


class Motor:
    def __init__(self, plc_ip='localhost', plc_port=502):
        self.MOTOR_CALISTIR_ADRESI = 11
        self.MOTOR_DURDUR_ADRESI = 12
        self.MOTOR_HIZ_ADRESI = 13
        self.client = ModbusTcpClient(plc_ip, port=plc_port)
    
    def connect(self):
        if self.client.connect():
            print("Sunucuya başarıyla bağlanıldı.")
            return True
        else:
            print("Sunucuya bağlantı başarısız.")
            return False
    
    def motor_calistir(self):
        self.client.write_register(self.MOTOR_CALISTIR_ADRESI, 1)
        time.sleep(0.2)
        print("Motor çalıştırıldı.")

    def set_speed(self, rpm):
        self.client.write_register(self.MOTOR_HIZ_ADRESI, rpm)
        print(f"Motor hızı ayarlandı: {rpm} rpm")

    def motor_durdur(self):
        self.client.write_register(self.MOTOR_DURDUR_ADRESI, 0)
        time.sleep(0.2)
        print("Motor durduruldu.")

    def disconnect(self):
        self.client.close()
        print("Sunucu bağlantısı kapatıldı.")


# ------------------ Ana Uygulama (MainApp) ------------------ #
class MainApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Reçete Sistemi")
        self.geometry("1100x900")
        self.configure(fg_color="#001428")  # Arka plan
        ctk.set_appearance_mode("dark")
        self.attributes("-alpha", 0.95)

        # Saat göstergesi
        self.clock_label = None

        # Kullanıcı veritabanı
        loaded_users = load_users_csv("users.csv")
        if loaded_users is not None:
            self.user_db = loaded_users
        else:
            self.user_db = {
                "admin": {
                    "password": "admin",
                    "role": "admin",
                    "permissions": {
                        "define": True,
                        "apply": True,
                        "list": True,
                        "user_mgmt": True
                    }
                },
                "operator1": {
                    "password": "1234",
                    "role": "operator",
                    "permissions": {
                        "define": False,
                        "apply": True,
                        "list": True,
                        "user_mgmt": False
                    }
                }
            }
            save_users_csv(self.user_db)

        self.current_user = None
        self.session_start_time = None

        # Giriş ekranı
        self.login_frame = LoginFrame(self)
        self.login_frame.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.detail_frame = None  # Reçete / Kullanıcı detaylarını göstermek için

    def login_success(self, username):
        self.current_user = username
        self.session_start_time = time.time()
        self.login_frame.destroy()
        self.recipe_manager = RecipeManager()
        self._build_main_ui()
        self.update_clock()  # Saati güncellemeye başla

    def _build_main_ui(self):
        # Ana grid
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)

        # Üst kısım: saat ve kullanıcı bilgisi
        top_frame = ctk.CTkFrame(self, fg_color="#001428")
        top_frame.grid(row=0, column=2, sticky="ne", padx=10, pady=10)

        self.clock_label = ctk.CTkLabel(top_frame, text="", font=("Roboto", 14, "bold"), text_color="#00feff")
        self.clock_label.pack(side="left", padx=(0,10))

        ctk.CTkLabel(top_frame, text="|", font=("Roboto", 14, "bold"), text_color="#00feff").pack(side="left", padx=(0,10))

        self.user_label = ctk.CTkLabel(top_frame, text=f"Kullanıcı: {self.current_user}",
                                       font=("Roboto", 14, "bold"), text_color="#00feff")
        self.user_label.pack(side="left")

        # Orta container
        self.container = ctk.CTkFrame(self, corner_radius=10, fg_color="#001428")
        self.container.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        # Ekranlar
        self.frames = {}
        define_frame = RecipeDefineFrame(self.container, self)
        apply_frame = RecipeApplyFrame(self.container, self)
        list_frame = RecipeListFrame(self.container, self)
        user_mgmt_frame = UserManagementFrame(self.container, self)

        self.frames["define"] = define_frame
        self.frames["apply"] = apply_frame
        self.frames["list"] = list_frame
        self.frames["user_mgmt"] = user_mgmt_frame

        define_frame.grid(row=0, column=0, sticky="nsew")
        apply_frame.grid(row=0, column=0, sticky="nsew")
        list_frame.grid(row=0, column=0, sticky="nsew")
        user_mgmt_frame.grid(row=0, column=0, sticky="nsew")

        # Sol menü (sidebar)
        self.sidebar = SidebarFrame(self)
        self.sidebar.grid(row=1, column=0, sticky="nswe", padx=5, pady=5)

        # Sağ taraf: detail_frame
        self.detail_frame = ctk.CTkFrame(self, corner_radius=10, width=250, fg_color="#001428")
        self.detail_frame.grid(row=1, column=2, sticky="nsew", padx=10, pady=10)

        self.show_default_frame()

    def update_clock(self):
        if self.clock_label and self.clock_label.winfo_exists():
            current_time = time.strftime("%H:%M:%S")
            self.clock_label.configure(text=current_time)
            self.after(1000, self.update_clock)


    def show_default_frame(self):
        perms = self.user_db[self.current_user]["permissions"]
        if perms.get("define", False):
            self.show_frame("define")
            return
        if perms.get("apply", False):
            self.show_frame("apply")
            return
        if perms.get("list", False):
            self.show_frame("list")
            return
        if perms.get("user_mgmt", False):
            self.show_frame("user_mgmt")
            return
        label = ctk.CTkLabel(self.container, text="Bu kullanıcıya hiçbir sayfa izni verilmemiş!", text_color="#00feff")
        label.grid(row=0, column=0, sticky="nsew")

    def show_frame(self, name):
        # Reçete detail frame temizliği (list dışındaysa)
        if name != "list":
            for widget in self.detail_frame.winfo_children():
                widget.destroy()
        # Kullanıcı yönetiminde detail paneli (edit) temizliği (user_mgmt dışındaysa)
        if name != "user_mgmt":
            self.frames["user_mgmt"].clear_user_edit_detail()

        frame = self.frames[name]
        frame.tkraise()

    # ---------- Reçete Detay Gösterimi (List ekranı için) ----------
    def show_recipe_detail(self, recipe):
        # Her halükarda detail_frame'i temizleyip dolduruyoruz
        for widget in self.detail_frame.winfo_children():
            widget.destroy()

        ctk.CTkLabel(self.detail_frame, text="Reçete Detayı / Düzenle", font=("Roboto", 16, "bold"),
                     text_color="#00feff").pack(pady=10)

        ctk.CTkLabel(self.detail_frame, text="Reçete Adı:", text_color="#00feff").pack()
        self.edit_name_var = ctk.StringVar(value=recipe["name"])
        name_entry = ctk.CTkEntry(self.detail_frame, textvariable=self.edit_name_var, fg_color="#003d61",
                                  text_color="white", placeholder_text="Yeni Reçete Adı")
        name_entry.pack(pady=5)

        self.edit_amount_vars = []
        amounts_frame = ctk.CTkFrame(self.detail_frame, fg_color="#001428")
        amounts_frame.pack(pady=5)

        # Malzeme isimleri
        material_names = self.recipe_manager.material_names
        for i in range(5):
            mat_name = material_names[i] if i < len(material_names) else f"Silo {i+1}"
            ctk.CTkLabel(amounts_frame, text=f"{mat_name}:", text_color="#00feff").grid(row=i, column=0, padx=5, pady=2, sticky="w")
            val = recipe["amounts"][i] if i < len(recipe["amounts"]) else 0.0
            var = ctk.StringVar(value=str(val))
            entry = ctk.CTkEntry(amounts_frame, textvariable=var, width=60, fg_color="#003d61",
                                 text_color="white", placeholder_text="0.000")
            entry.grid(row=i, column=1, padx=5, pady=2, sticky="ew")
            self.edit_amount_vars.append(var)

        # Mikser Süresi (dakika + saniye gösterimi)
        mixer_time = recipe.get("mixer_time", 0.0)
        mixer_min = int(mixer_time // 60)
        mixer_sec = int(mixer_time % 60)

        ctk.CTkLabel(self.detail_frame, text=f"Mikser Süresi: {mixer_min} dk {mixer_sec} sn", text_color="#00feff")\
            .pack(pady=5)

        ctk.CTkButton(self.detail_frame, text="Değişiklikleri Kaydet",
                      fg_color="#0070a8", hover_color="#00b1f9", text_color="white",
                      command=lambda: self.save_recipe_changes(recipe)).pack(pady=5)

        ctk.CTkButton(self.detail_frame, text="Reçeteyi Sil", fg_color="red", text_color="white",
                      command=lambda: self.delete_recipe(recipe)).pack(pady=5)

        used_str = "Evet" if recipe["used"] else "Hayır"
        duration_str = f"{recipe['duration']:.2f} sn" if recipe["duration"] else "N/A"
        info_label = ctk.CTkLabel(self.detail_frame, text=f"Kullanıldı: {used_str}\nSüre: {duration_str}",
                                  text_color="#00feff")
        info_label.pack(pady=5)

        ctk.CTkButton(self.detail_frame, text="Kodu Kopyala", corner_radius=10,
                      fg_color="#0070a8", hover_color="#00b1f9", text_color="white",
                      command=lambda: self.copy_code(recipe['code']))\
            .pack(pady=5)

        self.copy_label = ctk.CTkLabel(self.detail_frame, text="", text_color="white")
        self.copy_label.pack(pady=5)

    def copy_code(self, code):
        pyperclip.copy(code)
        self.copy_label.configure(text="Kopyalandı!")

    def save_recipe_changes(self, recipe):
        new_name = self.edit_name_var.get().strip()
        new_amounts = []
        try:
            for var in self.edit_amount_vars:
                val = float(var.get())
                new_amounts.append(val)
        except ValueError:
            ctk.CTkLabel(self.detail_frame, text="Miktar girişi hatalı!", fg_color="red").pack()
            return

        try:
            self.recipe_manager.update_recipe(recipe, new_name, new_amounts)
            ctk.CTkLabel(self.detail_frame, text="Değişiklikler kaydedildi!", fg_color="green").pack()
            self.frames["list"].refresh_list()
        except ValueError as e:
            ctk.CTkLabel(self.detail_frame, text=str(e), fg_color="red").pack()

    def delete_recipe(self, recipe):
        self.recipe_manager.remove_recipe(recipe)
        self.frames["list"].refresh_list()
        for widget in self.detail_frame.winfo_children():
            widget.destroy()

    def logout(self):
        print("Logout fonksiyonu başladı...")
        if self.current_user and self.session_start_time:
            usage_time = time.time() - self.session_start_time
            log_user_activity(self.current_user, "Logout", usage_time)
        print("Tüm frame'leri yok etmeden önce...")

        for f in self.frames.values():
            f.destroy()
        self.frames.clear()

        if hasattr(self, 'sidebar'):
            self.sidebar.destroy()
        if hasattr(self, 'user_label'):
            self.user_label.destroy()
        if hasattr(self, 'container'):
            self.container.destroy()
        if self.detail_frame:
            self.detail_frame.destroy()
        if self.clock_label:
            self.clock_label.destroy()

        print("Frame'ler yok edildi...")

        self.current_user = None
        self.session_start_time = None

        # Root'un geometry manager'ı grid ise:
        self.login_frame = LoginFrame(self)
        # Root'un row/col ayarları login için:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.login_frame.grid(row=0, column=0, sticky="nsew")

        print("Logout fonksiyonu bitti, login_frame oluşturuldu ve grid ile yerleştirildi...")



    def on_closing(self):
        """Pencere kapatılırken kullanım süresini CSV'ye kaydet."""
        if self.current_user and self.session_start_time:
            usage_time = time.time() - self.session_start_time
            log_user_activity(self.current_user, "Exit", usage_time)
        self.destroy()


# ------------------ LoginFrame: Saatli Giriş Ekranı ------------------ #
class LoginFrame(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="#001428")
        self.master = master

        # Login ekranında da sağ üstte saat gösterimi
        self.clock_label = None

        # Ana grid
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Üst kısım: saat
        top_frame = ctk.CTkFrame(self, fg_color="#001428")
        top_frame.grid(row=0, column=0, sticky="ne", padx=10, pady=10)

        self.clock_label = ctk.CTkLabel(top_frame, text="", font=("Roboto", 14, "bold"), text_color="#00feff")
        self.clock_label.pack(side="right")

        # Saat güncellemesi
        self.update_login_clock()

        # Alt kısım: Form
        form_container = ctk.CTkFrame(self, fg_color="#001428")
        form_container.grid(row=1, column=0, sticky="nsew")

        form_container.rowconfigure((0,1,2), weight=1)
        form_container.columnconfigure(0, weight=1)

        title_label = ctk.CTkLabel(form_container, text="Kullanıcı Girişi", font=("Roboto", 24), text_color="white")
        title_label.grid(row=0, column=0, pady=(40,10))

        form_frame = ctk.CTkFrame(form_container, fg_color="#001428")
        form_frame.grid(row=1, column=0, pady=10, padx=10)

        form_frame.columnconfigure(0, weight=1)
        form_frame.columnconfigure(1, weight=1)

        self.entry_username = ctk.CTkEntry(form_frame, placeholder_text="Kullanıcı Adı", width=220,
                                           fg_color="#003d61", text_color="white")
        self.entry_username.grid(row=0, column=0, columnspan=2, padx=10, pady=5)

        self.entry_password = ctk.CTkEntry(form_frame, placeholder_text="Şifre", show="*", width=220,
                                           fg_color="#003d61", text_color="white")
        self.entry_password.grid(row=1, column=0, columnspan=2, padx=10, pady=5)

        self.entry_password.bind("<Return>", lambda event: self.check_login())

        login_button = ctk.CTkButton(form_frame, text="Giriş Yap", corner_radius=10,
                                     fg_color="#0070a8", hover_color="#00b1f9", text_color="white",
                                     command=self.check_login)
        login_button.grid(row=2, column=0, columnspan=2, pady=10)

        self.result_label = ctk.CTkLabel(form_container, text="", text_color="white")
        self.result_label.grid(row=2, column=0, pady=5)

    def update_login_clock(self):
        if self.clock_label:
            current_time = time.strftime("%H:%M:%S")
            self.clock_label.configure(text=current_time)
        self.after(1000, self.update_login_clock)

    def check_login(self):
        username = self.entry_username.get().strip()
        password = self.entry_password.get().strip()

        if username in self.master.user_db:
            if self.master.user_db[username]["password"] == password:
                log_user_activity(username, "Login")
                self.master.login_success(username)
                return
        self.result_label.configure(text="Hatalı kullanıcı adı veya şifre!")


# ------------------ SidebarFrame ------------------ #
class SidebarFrame(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, corner_radius=10, fg_color="transparent")
        self.master = master
        self.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(self, text="Menüler", font=("Roboto", 20), text_color="white").grid(row=0, column=0, padx=20, pady=20)

        btn_style = {
            "corner_radius": 10,
            "fg_color":"transparent",
            "hover_color":"#002540",
            "text_color":"white"
        }

        perms = self.master.user_db[self.master.current_user]["permissions"]

        if perms.get("define", False):
            ctk.CTkButton(self, text="Reçete Tanımla",
                          command=lambda: self.master.show_frame("define"),
                          **btn_style).grid(row=1, column=0, padx=20, pady=5, sticky="ew")

        if perms.get("apply", False):
            ctk.CTkButton(self, text="Reçeteyi Uygula",
                          command=lambda: self.master.show_frame("apply"),
                          **btn_style).grid(row=2, column=0, padx=20, pady=5, sticky="ew")

        if perms.get("list", False):
            ctk.CTkButton(self, text="Reçete Listesi",
                          command=lambda: self.master.show_frame("list"),
                          **btn_style).grid(row=3, column=0, padx=20, pady=5, sticky="ew")

        if perms.get("user_mgmt", False):
            ctk.CTkButton(self, text="Kullanıcı Yönetimi",
                          command=lambda: self.master.show_frame("user_mgmt"),
                          **btn_style).grid(row=4, column=0, padx=20, pady=5, sticky="ew")

        # Oturumu Kapat (sarı)
        ctk.CTkButton(self, text="Oturumu Kapat",
                      corner_radius=10,
                      fg_color="#ffa500",
                      hover_color="#ffc000",
                      text_color="white",
                      command=self.logout).grid(row=6, column=0, padx=20, pady=5, sticky="ew")

        ctk.CTkButton(self, text="Acil Stop",
                      fg_color="red", text_color="white",
                      hover_color="#aa0000",
                      corner_radius=10,
                      command=self.emergency_stop).grid(row=8, column=0, padx=20, pady=20, sticky="s")

    def logout(self):
        self.master.logout()

    def emergency_stop(self):
        print("Acil Stop: Tüm sistem kapatılıyor!")
        if self.master.current_user:
            usage_time = time.time() - self.master.session_start_time
            log_user_activity(self.master.current_user, "EmergencyStop", usage_time)
        self.master.destroy()


# ------------------ Reçete Tanımlama Ekranı ------------------ #
class RecipeDefineFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="#001428")
        self.app = app
        self.recipe_manager = app.recipe_manager

        ctk.CTkLabel(self, text="Reçete Tanımlama", font=("Roboto", 24), text_color="white").pack(pady=20)

        form_frame = ctk.CTkFrame(self, fg_color="#001428")
        form_frame.pack(pady=10, padx=20)

        mat_names = self.recipe_manager.material_names

        # Reçete Adı
        ctk.CTkLabel(form_frame, text="Reçete Adı:", text_color="white").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.recipe_name_entry = ctk.CTkEntry(form_frame, width=250, placeholder_text="Yeni Reçete Adı",
                                             fg_color="#003d61", text_color="white")
        self.recipe_name_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        # 5 Malzeme
        self.magnitude_entries = []
        for i, mat_name in enumerate(mat_names):
            ctk.CTkLabel(form_frame, text=f"{mat_name} (gram):", text_color="white").grid(row=i+1, column=0, padx=10, pady=5, sticky="w")
            entry = ctk.CTkEntry(form_frame, width=250, placeholder_text="0.000",
                                 fg_color="#003d61", text_color="white")
            entry.grid(row=i+1, column=1, padx=10, pady=5, sticky="ew")
            self.magnitude_entries.append(entry)

        # Mikser Süresi (dakika + saniye)
        ctk.CTkLabel(form_frame, text="Mikser Süresi (dakika):", text_color="white").grid(row=6, column=0, padx=10, pady=5, sticky="w")
        self.mixer_min_entry = ctk.CTkEntry(form_frame, width=80, placeholder_text="Örn: 1",
                                            fg_color="#003d61", text_color="white")
        self.mixer_min_entry.grid(row=6, column=1, padx=10, pady=5, sticky="w")

        ctk.CTkLabel(form_frame, text="Mikser Süresi (saniye):", text_color="white").grid(row=7, column=0, padx=10, pady=5, sticky="w")
        self.mixer_sec_entry = ctk.CTkEntry(form_frame, width=80, placeholder_text="Örn: 30",
                                            fg_color="#003d61", text_color="white")
        self.mixer_sec_entry.grid(row=7, column=1, padx=10, pady=5, sticky="w")

        self.result_label = ctk.CTkLabel(self, text="", text_color="white")
        self.result_label.pack()

        # Reçete kodu gösterimi
        self.code_var = ctk.StringVar()
        self.code_entry = ctk.CTkEntry(self, textvariable=self.code_var, state="disabled",
                                       fg_color="#003d61", text_color="white")
        self.code_entry.pack(pady=5)

        self.copy_button = ctk.CTkButton(self, text="Kodu Kopyala", corner_radius=10,
                                         fg_color="#0070a8", hover_color="#00b1f9", text_color="white",
                                         command=self.copy_code)
        self.copy_button.pack(pady=5)

        ctk.CTkButton(self, text="Reçete Kodunu Oluştur", corner_radius=10,
                      fg_color="#0070a8", hover_color="#00b1f9", text_color="white",
                      command=self.create_code).pack(pady=10)

    def create_code(self):
        name = self.recipe_name_entry.get().strip()
        amounts = []
        for entry in self.magnitude_entries:
            val_str = entry.get().strip()
            try:
                val = round(float(val_str), 3) if val_str else 0
            except ValueError:
                self.result_label.configure(text="Hatalı miktar girişi!")
                return
            amounts.append(val)

        # Mikser Süresi
        try:
            mixer_min = float(self.mixer_min_entry.get().strip()) if self.mixer_min_entry.get().strip() else 0.0
            mixer_sec = float(self.mixer_sec_entry.get().strip()) if self.mixer_sec_entry.get().strip() else 0.0
            mixer_time = mixer_min * 60 + mixer_sec
        except ValueError:
            self.result_label.configure(text="Mikser süresi dakika/saniye hatalı!")
            return

        if not name:
            self.result_label.configure(text="Reçete adı boş olamaz!")
            return

        code = self.recipe_manager.create_recipe_code(amounts)
        try:
            self.recipe_manager.add_recipe(name, code, amounts, mixer_time)
            self.result_label.configure(
                text=f"Reçete '{name}' oluşturuldu.\nKod: {code}\nMikser Süresi: {int(mixer_min)} dk {int(mixer_sec)} sn"
            )
            self.code_var.set(code)
            self.app.frames["list"].refresh_list()
        except ValueError as e:
            self.result_label.configure(text=str(e))

    def copy_code(self):
        code = self.code_var.get()
        if code:
            pyperclip.copy(code)
            self.result_label.configure(text=f"Kod kopyalandı: {code}")
        else:
            self.result_label.configure(text="Henüz bir kod oluşturulmadı!")


# ------------------ Reçete Uygulama Ekranı ------------------ #
class RecipeApplyFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="#001428")
        self.app = app
        self.recipe_manager = app.recipe_manager

        ctk.CTkLabel(self, text="Reçete Uygulama", font=("Roboto", 24), text_color="white").pack(pady=20)

        form_frame = ctk.CTkFrame(self, fg_color="#001428")
        form_frame.pack(pady=10, padx=20)

        ctk.CTkLabel(form_frame, text="Reçete Kodunu Girin:", text_color="white").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.recipe_code_entry = ctk.CTkEntry(form_frame, width=250, placeholder_text="Reçete Kodu",
                                             fg_color="#003d61", text_color="white")
        self.recipe_code_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        #
        self.start_button = ctk.CTkButton(self, text="İşlemi Başlat", command=self.start_process)
        self.start_button.pack(pady=10)


        self.result_label = ctk.CTkLabel(self, text="", text_color="white")
        self.result_label.pack(pady=5)

    def start_process(self):
        recipe_code = self.recipe_code_entry.get().strip()
        if self.recipe_manager.decode_recipe_code(recipe_code) is None:
            self.result_label.configure(text="Reçete bulunamadı!")
            return
        # butonu devre dışı bırak
        self.start_button.configure(state="disabled")
        # iş parçacığı başlat
        threading.Thread(target=self._run_recipe, args=(recipe_code,), daemon=True).start()
    
    def _run_recipe(self, recipe_code):
        amounts = self.recipe_manager.decode_recipe_code(recipe_code)
        mixer_time = self.recipe_manager.get_mixer_time(recipe_code)
        client = ModbusTcpClient(self.recipe_manager.plc_ip, port=self.recipe_manager.plc_port)
        motor  = Motor(self.recipe_manager.plc_ip, self.recipe_manager.plc_port)
        start  = time.time()
        try:
            if not client.connect() or not motor.connect():
                self._update_label("Sunucuya veya motora bağlanılamadı!")
                return

            for tur in range(2):
                self._update_label(f"{tur+1}. tur malzeme alınıyor…")
                for i, qty in enumerate(amounts):
                    if qty==0: continue
                    motor.motor_calistir(); motor.set_speed(2500)
                    client.write_register(self.recipe_manager.silo_addresses[i], 1)
                    time.sleep(1)
                    client.write_register(self.recipe_manager.silo_addresses[i], 0)
                    motor.motor_durdur()

            self._update_label("Karışım teraziden boşaltılıyor…")
            time.sleep(2)

            if mixer_time>0:
                m, s = divmod(mixer_time, 60)
                self._update_label(f"Mikser çalışıyor ({int(m)}dk {int(s)}sn)…")
                time.sleep(mixer_time)
                self._update_label("Mikser durdu.")

            duration = time.time() - start
            self.recipe_manager.update_recipe_status(recipe_code, used=True, duration=duration)
            self._update_label(f"Tüm işlemler tamamlandı. Süre: {duration:.2f}s")

        except Exception as e:
            self._update_label(f"Hata: {e}")
        finally:
            motor.disconnect(); client.close()
            # butonu tekrar aktif et
            self.after(0, lambda: self.start_button.configure(state="normal"))

    def _update_label(self, text):
        self.after(0, lambda: self.result_label.configure(text=text))


# ------------------ Reçete Listesi Ekranı ------------------ #
class RecipeListFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="#001428")
        self.app = app
        self.recipe_manager = app.recipe_manager

        ctk.CTkLabel(self, text="Reçete Listesi", font=("Roboto", 24), text_color="white").pack(pady=20)

        search_frame = ctk.CTkFrame(self, fg_color="#001428")
        search_frame.pack(pady=5, padx=20, fill="x")
        search_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(search_frame, text="Ara:", text_color="white").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.search_entry = ctk.CTkEntry(search_frame, fg_color="#003d61", text_color="white",
                                        placeholder_text="Reçete Adı")
        self.search_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        self.search_entry.bind("<KeyRelease>", self.filter_recipes)

        self.list_container = ctk.CTkScrollableFrame(self, fg_color="#001428")
        self.list_container.pack(pady=10, padx=20, fill="both", expand=True)

        self.refresh_list()
    
    def filter_recipes(self, event):
        query = self.search_entry.get().lower()
        for widget in self.list_container.winfo_children():
            widget.destroy()
        for recipe in self.recipe_manager.recipe_list:
            if query in recipe["name"].lower():
                self._create_recipe_button(recipe)

    def refresh_list(self):
        for widget in self.list_container.winfo_children():
            widget.destroy()
        for recipe in self.recipe_manager.recipe_list:
            self._create_recipe_button(recipe)
    
    def _create_recipe_button(self, recipe):
        status = "Evet" if recipe["used"] else "Hayır"
        button_text = f"{recipe['name']} - Hazırlandı: {status}"
        btn_style = {
            "corner_radius": 10,
            "fg_color": "transparent",
            "hover_color": "#002540",
            "text_color": "white",
            "border_width": 1,
            "border_color": "#0070a8"
        }
        btn = ctk.CTkButton(
            self.list_container, 
            text=button_text,
            command=lambda r=recipe: self.app.show_recipe_detail(r),
            **btn_style
        )
        btn.pack(pady=5, fill="x", padx=10)


# ------------------ Kullanıcı Yönetimi Ekranı ------------------ #
class UserManagementFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="#001428")
        self.app = app

        self.scroll_container = ctk.CTkScrollableFrame(self, corner_radius=10, fg_color="#001428")
        self.scroll_container.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(self.scroll_container, text="Kullanıcı Yönetimi", font=("Roboto", 24), text_color="white").pack(pady=20)

        self.add_user_frame = ctk.CTkFrame(self.scroll_container, fg_color="#001428")
        self.add_user_frame.pack(pady=10, padx=20, fill="x")
        self.add_user_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.add_user_frame, text="Kullanıcı Adı:", text_color="white").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.entry_username = ctk.CTkEntry(self.add_user_frame, fg_color="#003d61", text_color="white",
                                          placeholder_text="Kullanıcı Adı")
        self.entry_username.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(self.add_user_frame, text="Şifre:", text_color="white").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.entry_password = ctk.CTkEntry(self.add_user_frame, fg_color="#003d61", text_color="white",
                                          placeholder_text="Şifre")
        self.entry_password.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(self.add_user_frame, text="Reçete Tanımla (define):", text_color="white").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.var_define = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.add_user_frame, variable=self.var_define, text="", fg_color="#001428").grid(row=2, column=1, sticky="w")

        ctk.CTkLabel(self.add_user_frame, text="Reçete Uygula (apply):", text_color="white").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.var_apply = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.add_user_frame, variable=self.var_apply, text="", fg_color="#001428").grid(row=3, column=1, sticky="w")

        ctk.CTkLabel(self.add_user_frame, text="Reçete Listesi (list):", text_color="white").grid(row=4, column=0, padx=10, pady=5, sticky="w")
        self.var_list = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.add_user_frame, variable=self.var_list, text="", fg_color="#001428").grid(row=4, column=1, sticky="w")

        ctk.CTkLabel(self.add_user_frame, text="Kullanıcı Yönetimi (user_mgmt):", text_color="white").grid(row=5, column=0, padx=10, pady=5, sticky="w")
        self.var_user_mgmt = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.add_user_frame, variable=self.var_user_mgmt, text="", fg_color="#001428").grid(row=5, column=1, sticky="w")

        ctk.CTkButton(self.add_user_frame, text="Kullanıcı Ekle", corner_radius=10,
                      fg_color="#0070a8", hover_color="#00b1f9", text_color="white",
                      command=self.add_user).grid(row=6, column=0, columnspan=2, pady=10)

        self.result_label = ctk.CTkLabel(self.scroll_container, text="", text_color="white")
        self.result_label.pack(pady=5)

        ctk.CTkLabel(self.scroll_container, text="Kayıtlı Kullanıcılar", font=("Roboto", 20), text_color="white").pack(pady=10)
        self.user_list_container = ctk.CTkScrollableFrame(self.scroll_container, width=600, height=300, fg_color="#001428")
        self.user_list_container.pack(pady=5, padx=20, fill="both", expand=True)

        # Kullanıcı düzenleme => detail_frame'e yansıtacağız
        self.selected_user = None

        self.refresh_user_list()

    def clear_user_edit_detail(self):
        """UserManagement ekranından çıkıldığında, detail_frame'i temizle."""
        if self.app.detail_frame:
            for w in self.app.detail_frame.winfo_children():
                w.destroy()
        self.selected_user = None

    def add_user(self):
        uname = self.entry_username.get().strip()
        pw = self.entry_password.get().strip()
        if uname == "" or pw == "":
            self.result_label.configure(text="Kullanıcı adı ve şifre boş olamaz!")
            return
        if uname in self.app.user_db:
            self.result_label.configure(text="Bu kullanıcı adı zaten var!")
            return

        new_permissions = {
            "define": self.var_define.get(),
            "apply": self.var_apply.get(),
            "list": self.var_list.get(),
            "user_mgmt": self.var_user_mgmt.get()
        }

        self.app.user_db[uname] = {
            "password": pw,
            "role": "operator",
            "permissions": new_permissions
        }
        save_users_csv(self.app.user_db)

        self.result_label.configure(text=f"{uname} kullanıcısı eklendi.")
        self.refresh_user_list()

    def refresh_user_list(self):
        for widget in self.user_list_container.winfo_children():
            widget.destroy()

        for uname, data in self.app.user_db.items():
            btn_text = f"{uname} (role: {data['role']})"
            ctk.CTkButton(self.user_list_container, text=btn_text,
                          fg_color="transparent", hover_color="#002540", text_color="white",
                          command=lambda u=uname: self.show_user_edit_detail(u))\
                .pack(pady=5, fill="x", padx=10)

    def show_user_edit_detail(self, uname):
        """Kullanıcı bilgilerini detail_frame'e bas."""
        self.selected_user = uname
        # detail_frame'i temizle
        for w in self.app.detail_frame.winfo_children():
            w.destroy()

        data = self.app.user_db[uname]

        ctk.CTkLabel(self.app.detail_frame, text=f"Kullanıcı Düzenle: {uname}",
                     font=("Roboto", 16, "bold"), text_color="#00feff").pack(pady=10)

        # Şifre
        ctk.CTkLabel(self.app.detail_frame, text="Şifre:", text_color="white").pack()
        self.edit_password_var = ctk.StringVar(value=data["password"])
        ctk.CTkEntry(self.app.detail_frame, textvariable=self.edit_password_var,
                     fg_color="#003d61", text_color="white").pack(pady=5)

        # Permissions
        self.edit_define_var = ctk.BooleanVar(value=data["permissions"]["define"])
        self.edit_apply_var = ctk.BooleanVar(value=data["permissions"]["apply"])
        self.edit_list_var = ctk.BooleanVar(value=data["permissions"]["list"])
        self.edit_user_mgmt_var = ctk.BooleanVar(value=data["permissions"]["user_mgmt"])

        ctk.CTkCheckBox(self.app.detail_frame, text="Reçete Tanımla (define)", variable=self.edit_define_var,
                        fg_color="#001428", text_color="white").pack(pady=2, anchor="w")
        ctk.CTkCheckBox(self.app.detail_frame, text="Reçete Uygula (apply)", variable=self.edit_apply_var,
                        fg_color="#001428", text_color="white").pack(pady=2, anchor="w")
        ctk.CTkCheckBox(self.app.detail_frame, text="Reçete Listesi (list)", variable=self.edit_list_var,
                        fg_color="#001428", text_color="white").pack(pady=2, anchor="w")
        ctk.CTkCheckBox(self.app.detail_frame, text="Kullanıcı Yönetimi (user_mgmt)", variable=self.edit_user_mgmt_var,
                        fg_color="#001428", text_color="white").pack(pady=2, anchor="w")

        ctk.CTkButton(self.app.detail_frame, text="Kaydet", fg_color="#0070a8", hover_color="#00b1f9",
                      text_color="white", command=self.save_user_changes)\
            .pack(pady=5)
        ctk.CTkButton(self.app.detail_frame, text="Sil", fg_color="red", text_color="white",
                      command=self.delete_user)\
            .pack(pady=5)

        self.edit_result_label = ctk.CTkLabel(self.app.detail_frame, text="", text_color="white")
        self.edit_result_label.pack(pady=5)

    def save_user_changes(self):
        if not self.selected_user:
            return
        data = self.app.user_db[self.selected_user]
        new_pw = self.edit_password_var.get().strip()
        if new_pw == "":
            self.edit_result_label.configure(text="Şifre boş olamaz!", fg_color="red")
            return

        new_perms = {
            "define": self.edit_define_var.get(),
            "apply": self.edit_apply_var.get(),
            "list": self.edit_list_var.get(),
            "user_mgmt": self.edit_user_mgmt_var.get()
        }

        data["password"] = new_pw
        data["permissions"] = new_perms
        save_users_csv(self.app.user_db)

        self.edit_result_label.configure(text="Değişiklikler kaydedildi!", fg_color="green")
        self.refresh_user_list()

    def delete_user(self):
        if not self.selected_user:
            return
        if self.selected_user == "admin":
            self.edit_result_label.configure(text="Admin kullanıcısı silinemez!", fg_color="red")
            return
        del self.app.user_db[self.selected_user]
        save_users_csv(self.app.user_db)

        self.edit_result_label.configure(text=f"{self.selected_user} silindi.", fg_color="green")
        self.selected_user = None

        # Detail'i temizle
        for w in self.app.detail_frame.winfo_children():
            w.destroy()

        self.refresh_user_list()


# ------------------ Program Giriş Noktası ------------------ #
if __name__ == "__main__":
    app = MainApp()
    app.mainloop()
