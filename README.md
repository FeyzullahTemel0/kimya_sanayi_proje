# Reçete Sistemi

**Basit, esnek ve izlenebilir bir kimyasal reçete yönetim arayüzü**

---

## 📦 Genel Bakış

Bu proje, endüstriyel PLC (Modbus TCP) kontrollü malzeme dozajlama ve karıştırma sürecini yönetmek için hazırlanmış bir masaüstü uygulamasıdır.  
- **Reçete Tanımlama**: Gram cinsinden malzeme ölçülerini girip, SHA-256 tabanlı benzersiz kod oluşturma.  
- **Reçete Uygulama**: PLC’ye komut göndererek otomatik dozajlama ve mikser kontrollü karıştırma.  
- **Reçete Listesi & Detay**: Hazırlanan reçeteleri listeleme, düzenleme, silme ve kullanım istatistiklerini görüntüleme.  
- **Kullanıcı Yönetimi**: Rol & izin bazlı (tanımlama, uygulama, listeleme, kullanıcı yönetimi) erişim kontrolü.  
- **Kullanıcı Aktivite Kaydı**: Giriş, çıkış ve acil durum kayıtlarını `user_activity.csv` dosyasında tarih/saat bazlı saklama.

---

## 🚀 Kurulum & Çalıştırma

1. **Gereksinimler**  
   - Python 3.9 veya üzeri  
   - Windows/Linux/macOS ortamı  

2. **Klon & Paket Yükleme**  
   ```bash
   git clone https://github.com/your-org/recete-sistemi.git
   cd recete-sistemi
   pip install --upgrade pip
   pip install -r requirements.txt
