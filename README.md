Update 2.0 :
1.  Fixing Bug maps_place_name excel
2.  Bar progress persentase scrapping
3.  spesifik 'yogyakarta' di pencarian maps. contoh {nama toko} + 'yogyakarta'. untuk fokus pencarian toko di Yogyakarta bukan cabang lain provinsi
4.  fixing minor bug
5.  Excel Tersimpan di folder yang sama (belum dirapikan untuk masuk ke folder data)

*Note: Khusus Blibli tidak ada filter 'Bantul' sehingga menggunakan 'Yogyakarta', Tokopedia dan Olx filter tetap 'Bantul'. Continuously tracking down and resolving bugs 

<img width="1072" height="797" alt="image" src="https://github.com/user-attachments/assets/f16c2a75-a965-41fc-8635-c91a12b47027" />

Cara Membuat exe :

1. cek apakah sudah terinstal pyinstaller : 
  'pip install pyinstaller'

2. Jalankan perintah compile / build :
  'pyinstaller --noconfirm --onedir --windowed --collect-all customtkinter --collect-all playwright app.py'

3. Pindahkan File GeoJSON
     -Buka folder proyek Anda.
   - Salin/Copy file idsls fix.geojson.
   - Buka folder dist -> buka folder app.
   - Paste file idsls fix.geojson tersebut di dalam folder app, sejajar dengan file app.exe
  
4. Zip folder App
